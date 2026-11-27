"""The ledger's hash chain: how an entry is hashed, linked and checked.

Pure rules: no IO and no clock.

What an entry's hash covers. A canonical JSON encoding (sorted keys, fixed separators, ASCII
only, the same approach as the kernel's version stamp) of the scheme name, the entry id, the
entry type, the payload, the digest of the version stamp and the previous hash. Everything the
writer supplies is covered. The payload may not hold floats, so the bytes hashed do not depend
on how a database or a parser rounds a number.

What it does not cover. The sequence and recorded_at are assigned by the database as the row
is written, after the hash is fixed, so they cannot be in it. The sequence is held in order by
the chain itself: entries are linked by hash, never by sequence + 1 (a failed insert leaves a
gap in the sequence), and a chain whose sequence does not rise along the links is reported.
recorded_at is not tamper evident here. Anything that must be trusted as a time lives in the
payload, which is hashed (a decision's decided_at), and the signed checkpoint that a later task
adds pins the head, and with it everything before it, at a time the repository cannot change.

What verification finds. The first entry links to a fixed genesis hash. Walking from it by hash, it reports an entry whose
content no longer matches its hash, a missing, duplicated or foreign link, a fork, an entry the
walk cannot reach, and a sequence that does not rise. A chain read from the table alone cannot
show that entries were cut off the end, or that the whole suffix was rewritten and re-hashed:
that needs the anchor (the head hash from a checkpoint kept outside the table). Given the
anchor, any change to any entry, however carefully the hashes after it are recomputed, makes the
head differ from the anchor.
"""

import hashlib
import json
from collections.abc import Sequence

from pydantic import JsonValue

from src.engine.kernel.version_stamp import stamp_digest
from src.models.kernel_models import VersionStamp
from src.models.ledger_models import (
    GENESIS_HASH,
    ChainAnchor,
    ChainProblem,
    ChainProblemType,
    ChainVerification,
    LedgerEntryDraft,
    SealedLedgerEntry,
    StoredLedgerEntry,
)

_ENTRY_SCHEME = "mandate.ledger.entry.v1"


def canonical_entry_json(
    entry_id: str,
    entry_type: str,
    payload: dict[str, JsonValue],
    version_stamp: VersionStamp,
    previous_hash: str,
) -> str:
    """Encode what an entry's hash covers; equal content always encodes to equal text."""
    _require_exact_json(payload)
    content: dict[str, JsonValue] = {
        "scheme": _ENTRY_SCHEME,
        "entry_id": entry_id,
        "entry_type": entry_type,
        "payload": payload,
        "version_stamp_digest": stamp_digest(version_stamp),
        "previous_hash": previous_hash,
    }
    return json.dumps(content, sort_keys=True, separators=(",", ":"), allow_nan=False)


def compute_entry_hash(
    entry_id: str,
    entry_type: str,
    payload: dict[str, JsonValue],
    version_stamp: VersionStamp,
    previous_hash: str,
) -> str:
    """Return the hex SHA-256 of the canonical encoding."""
    encoded = canonical_entry_json(entry_id, entry_type, payload, version_stamp, previous_hash)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def seal_entry(draft: LedgerEntryDraft, previous_hash: str) -> SealedLedgerEntry:
    """Link a draft to the entry before it and give it its own hash."""
    entry_hash = compute_entry_hash(
        str(draft.entry_id),
        draft.entry_type,
        draft.payload,
        draft.version_stamp,
        previous_hash,
    )
    return SealedLedgerEntry(
        entry_id=draft.entry_id,
        entry_type=draft.entry_type,
        payload=draft.payload,
        version_stamp=draft.version_stamp,
        previous_hash=previous_hash,
        entry_hash=entry_hash,
    )


def entry_hash_problem(entry: StoredLedgerEntry) -> ChainProblem | None:
    """Say what is wrong with one entry's own hash, or None when it holds."""
    if entry.entry_hash is None:
        return _problem(ChainProblemType.UNHASHED_ENTRY, entry, "the entry has no hash")
    if entry.version_stamp is None:
        return _problem(ChainProblemType.MISSING_STAMP, entry, "the entry has no version stamp")
    if entry.previous_hash is None:
        return _problem(ChainProblemType.MISSING_LINK, entry, "the entry has no previous hash")
    expected = compute_entry_hash(
        str(entry.entry_id),
        entry.entry_type,
        entry.payload,
        entry.version_stamp,
        entry.previous_hash,
    )
    if expected != entry.entry_hash:
        return _problem(
            ChainProblemType.HASH_MISMATCH, entry, "the entry's content does not match its hash"
        )
    return None


def verify_chain(
    entries: Sequence[StoredLedgerEntry], anchor: ChainAnchor | None = None
) -> ChainVerification:
    """Walk the chain by hash from its first entry and report everything wrong with it.

    The order of `entries` carries no meaning. Pass the anchor to also detect entries cut off
    the end and a suffix rewritten with recomputed hashes.
    """
    problems: list[ChainProblem] = []
    for entry in entries:
        own = entry_hash_problem(entry)
        if own is not None:
            problems.append(own)

    first_previous = GENESIS_HASH if anchor is None else anchor.first_previous_hash
    by_previous: dict[str | None, list[StoredLedgerEntry]] = {}
    seen_hashes: set[str] = set()
    for entry in entries:
        by_previous.setdefault(entry.previous_hash, []).append(entry)
        if entry.entry_hash is not None:
            if entry.entry_hash in seen_hashes:
                problems.append(
                    _problem(ChainProblemType.DUPLICATE_HASH, entry, "the hash appears twice")
                )
            seen_hashes.add(entry.entry_hash)
    for previous, children in by_previous.items():
        for extra in sorted(children, key=lambda item: item.sequence)[1:]:
            problems.append(
                _problem(
                    ChainProblemType.FORK,
                    extra,
                    f"more than one entry follows {previous}",
                )
            )

    walked = _walk(by_previous, first_previous)
    if entries and not walked:
        problems.append(
            ChainProblem(
                problem=ChainProblemType.BAD_START,
                sequence=None,
                detail="no entry links to the expected start of the chain",
            )
        )
    walked_ids = {entry.entry_id for entry in walked}
    for entry in entries:
        if entry.entry_id not in walked_ids:
            problems.append(
                _problem(
                    ChainProblemType.UNREACHABLE_ENTRY, entry, "no chain of links reaches the entry"
                )
            )
    for before, after in zip(walked, walked[1:]):
        if after.sequence <= before.sequence:
            problems.append(
                _problem(ChainProblemType.SEQUENCE_ORDER, after, "the sequence does not rise")
            )
    if anchor is not None:
        head = walked[-1].entry_hash if walked else first_previous
        if head != anchor.head_hash:
            problems.append(
                ChainProblem(
                    problem=ChainProblemType.HEAD_MISMATCH,
                    sequence=None,
                    detail="the chain does not end at the anchored head",
                )
            )
    return ChainVerification(entries_checked=len(entries), problems=tuple(problems))


def _walk(
    by_previous: dict[str | None, list[StoredLedgerEntry]], first_previous: str
) -> list[StoredLedgerEntry]:
    """Follow the links from the start, taking the lowest sequence at a fork, never looping."""
    walked: list[StoredLedgerEntry] = []
    visited: set[str] = set()
    link = first_previous
    while True:
        children = by_previous.get(link)
        if not children:
            return walked
        step = min(children, key=lambda item: item.sequence)
        if step.entry_hash is None or step.entry_hash in visited:
            walked.append(step)
            return walked
        visited.add(step.entry_hash)
        walked.append(step)
        link = step.entry_hash


def _problem(kind: ChainProblemType, entry: StoredLedgerEntry, detail: str) -> ChainProblem:
    return ChainProblem(problem=kind, sequence=entry.sequence, detail=detail)


def _require_exact_json(value: JsonValue) -> None:
    """Refuse a float anywhere in a payload: its text can differ between parsers."""
    if isinstance(value, float):
        raise ValueError("a ledger payload may not hold a float; use an integer or a string")
    if isinstance(value, dict):
        for item in value.values():
            _require_exact_json(item)
    elif isinstance(value, list):
        for item in value:
            _require_exact_json(item)
