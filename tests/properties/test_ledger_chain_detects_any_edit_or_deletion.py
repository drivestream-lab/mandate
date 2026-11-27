"""The chain check finds any edited, deleted, inserted or reordered entry, across generated chains.

Two strengths of check are tested. Read from the table alone, a chain shows every change except
two that look like honest history: entries cut off the end, and a suffix rewritten with its
hashes recomputed. With the head hash from a checkpoint kept outside the table (the anchor), no
change at all goes unseen.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from hypothesis import assume, given, settings, strategies as st
from pydantic import JsonValue

from src.engine.ledger.hash_chain import seal_entry, verify_chain
from src.models.kernel_models import NamedVersion, VersionStamp
from src.models.ledger_models import (
    GENESIS_HASH,
    ChainAnchor,
    LedgerEntryDraft,
    StoredLedgerEntry,
)

_BASE_TIME = datetime(2026, 11, 27, tzinfo=UTC)

_json_values: st.SearchStrategy[JsonValue] = st.recursive(
    st.none() | st.booleans() | st.integers(-(10**9), 10**9) | st.text(max_size=20),
    lambda children: st.lists(children, max_size=3)
    | st.dictionaries(st.text(max_size=8), children, max_size=3),
    max_leaves=6,
)
_payloads: st.SearchStrategy[dict[str, JsonValue]] = st.dictionaries(
    st.text(max_size=8), _json_values, max_size=4
)
_entry_types = st.sampled_from(["decision", "correction", "other"])
_hashes = st.text(alphabet="0123456789abcdef", min_size=64, max_size=64)


def _stamp(release: str) -> VersionStamp:
    return VersionStamp(
        contract="1",
        block_versions=(NamedVersion(name="review", version="2"),),
        skills=(NamedVersion(name="spec-read", version="5"),),
        rules="r1",
        agent_setup="a1",
        policy_revision="p1",
        mandate_release=release,
    )


_stamps = st.sampled_from(["0.1.0", "0.2.0", "0.3.0"]).map(_stamp)


@st.composite
def _chains(draw: st.DrawFn, min_size: int = 1) -> list[StoredLedgerEntry]:
    """A genuine chain: sealed one on the next, with gaps in the sequence as failed inserts leave."""
    size = draw(st.integers(min_value=min_size, max_value=8))
    gaps = draw(st.lists(st.integers(1, 5), min_size=size, max_size=size))
    entries: list[StoredLedgerEntry] = []
    previous = GENESIS_HASH
    sequence = 0
    for index in range(size):
        sequence += gaps[index]
        sealed = seal_entry(
            LedgerEntryDraft(
                entry_id=UUID(int=index + 1),
                entry_type=draw(_entry_types),
                payload=draw(_payloads),
                version_stamp=draw(_stamps),
            ),
            previous,
        )
        entries.append(_stored(sealed.model_dump(), sequence, index))
        previous = sealed.entry_hash
    return entries


def _stored(values: dict[str, object], sequence: int, index: int) -> StoredLedgerEntry:
    return StoredLedgerEntry.model_validate(
        {**values, "sequence": sequence, "recorded_at": _BASE_TIME + timedelta(seconds=index)}
    )


def _anchor(chain: list[StoredLedgerEntry]) -> ChainAnchor:
    head = chain[-1].entry_hash
    assert head is not None
    return ChainAnchor(head_hash=head)


def _reseal_from(
    chain: list[StoredLedgerEntry], index: int, replacement: LedgerEntryDraft
) -> list[StoredLedgerEntry]:
    """Replace one entry and recompute every hash after it: the most careful rewrite there is."""
    rewritten = list(chain[:index])
    previous = rewritten[-1].entry_hash if rewritten else GENESIS_HASH
    assert previous is not None
    drafts = [replacement] + [
        LedgerEntryDraft(
            entry_id=entry.entry_id,
            entry_type=entry.entry_type,
            payload=entry.payload,
            version_stamp=_required(entry.version_stamp),
        )
        for entry in chain[index + 1 :]
    ]
    for offset, draft in enumerate(drafts):
        sealed = seal_entry(draft, previous)
        position = index + offset
        rewritten.append(_stored(sealed.model_dump(), chain[position].sequence, position))
        previous = sealed.entry_hash
    return rewritten


def _required(stamp: VersionStamp | None) -> VersionStamp:
    assert stamp is not None
    return stamp


@pytest.mark.req("REQ-55")
@given(chain=_chains(), data=st.data())
def test_a_genuine_chain_verifies_in_any_input_order(
    chain: list[StoredLedgerEntry], data: st.DataObject
) -> None:
    shuffled = data.draw(st.permutations(chain))
    assert verify_chain(shuffled).is_intact
    assert verify_chain(shuffled, _anchor(chain)).is_intact


@pytest.mark.req("REQ-55")
@given(chain=_chains(), data=st.data())
def test_an_edited_entry_is_found_from_the_table_alone(
    chain: list[StoredLedgerEntry], data: st.DataObject
) -> None:
    index = data.draw(st.integers(0, len(chain) - 1))
    field = data.draw(
        st.sampled_from(
            ["payload", "entry_type", "version_stamp", "entry_id", "previous_hash", "entry_hash"]
        )
    )
    original = chain[index]
    replacement: dict[str, object] = {
        "payload": data.draw(_payloads),
        "entry_type": data.draw(_entry_types),
        "version_stamp": data.draw(_stamps),
        "entry_id": UUID(int=data.draw(st.integers(100, 200))),
        "previous_hash": data.draw(_hashes),
        "entry_hash": data.draw(_hashes),
    }
    assume(replacement[field] != getattr(original, field))
    edited = list(chain)
    edited[index] = original.model_copy(update={field: replacement[field]})
    assert not verify_chain(edited).is_intact
    assert not verify_chain(edited, _anchor(chain)).is_intact


@pytest.mark.req("REQ-55")
@given(chain=_chains(), data=st.data())
def test_an_edit_with_every_later_hash_recomputed_is_found_with_the_anchor(
    chain: list[StoredLedgerEntry], data: st.DataObject
) -> None:
    index = data.draw(st.integers(0, len(chain) - 1))
    original = chain[index]
    payload: dict[str, JsonValue] = data.draw(_payloads)
    assume(payload != original.payload)
    forged = _reseal_from(
        chain,
        index,
        LedgerEntryDraft(
            entry_id=original.entry_id,
            entry_type=original.entry_type,
            payload=payload,
            version_stamp=_required(original.version_stamp),
        ),
    )
    assert not verify_chain(forged, _anchor(chain)).is_intact


@pytest.mark.req("REQ-55")
@given(chain=_chains(), data=st.data())
def test_a_deleted_entry_is_found_with_the_anchor_and_mid_chain_without_it(
    chain: list[StoredLedgerEntry], data: st.DataObject
) -> None:
    index = data.draw(st.integers(0, len(chain) - 1))
    remaining = chain[:index] + chain[index + 1 :]
    assert not verify_chain(remaining, _anchor(chain)).is_intact
    if index < len(chain) - 1:
        assert not verify_chain(remaining).is_intact


@pytest.mark.req("REQ-55")
@given(chain=_chains(), data=st.data())
def test_an_inserted_entry_is_found_with_the_anchor_and_before_the_end_without_it(
    chain: list[StoredLedgerEntry], data: st.DataObject
) -> None:
    index = data.draw(st.integers(0, len(chain)))
    previous = chain[index - 1].entry_hash if index else GENESIS_HASH
    assert previous is not None
    forged = seal_entry(
        LedgerEntryDraft(
            entry_id=UUID(int=10_000),
            entry_type=data.draw(_entry_types),
            payload=data.draw(_payloads),
            version_stamp=data.draw(_stamps),
        ),
        previous,
    )
    sequence = chain[index - 1].sequence + 1 if index else 0
    inserted = chain[:index] + [_stored(forged.model_dump(), sequence, index)] + chain[index:]
    assert not verify_chain(inserted, _anchor(chain)).is_intact
    if index < len(chain):
        assert not verify_chain(inserted).is_intact


@pytest.mark.req("REQ-55")
@given(chain=_chains(min_size=2), data=st.data())
def test_reordered_entries_are_found_from_the_table_alone(
    chain: list[StoredLedgerEntry], data: st.DataObject
) -> None:
    first = data.draw(st.integers(0, len(chain) - 1))
    second = data.draw(st.integers(0, len(chain) - 1))
    assume(first != second)
    reordered = list(chain)
    reordered[first] = chain[first].model_copy(update={"sequence": chain[second].sequence})
    reordered[second] = chain[second].model_copy(update={"sequence": chain[first].sequence})
    assert not verify_chain(reordered).is_intact
    assert not verify_chain(reordered, _anchor(chain)).is_intact


@pytest.mark.req("REQ-55")
@settings(max_examples=50)
@given(chain=_chains(min_size=2), data=st.data())
def test_entries_cut_off_the_end_need_the_anchor_to_be_seen(
    chain: list[StoredLedgerEntry], data: st.DataObject
) -> None:
    kept = data.draw(st.integers(1, len(chain) - 1))
    shortened = chain[:kept]
    assert verify_chain(shortened).is_intact
    assert not verify_chain(shortened, _anchor(chain)).is_intact


@pytest.mark.req("REQ-55")
def test_an_empty_ledger_matches_only_the_genesis_anchor() -> None:
    assert verify_chain([], ChainAnchor(head_hash=GENESIS_HASH)).is_intact
    assert not verify_chain([], ChainAnchor(head_hash="a" * 64)).is_intact


@pytest.mark.req("REQ-55")
@settings(max_examples=50)
@given(chain=_chains(), data=st.data())
def test_a_rewritten_suffix_looks_genuine_without_the_anchor(
    chain: list[StoredLedgerEntry], data: st.DataObject
) -> None:
    """The reason a checkpoint outside the table is needed: the table alone cannot show this."""
    index = data.draw(st.integers(0, len(chain) - 1))
    original = chain[index]
    payload: dict[str, JsonValue] = data.draw(_payloads)
    assume(payload != original.payload)
    forged = _reseal_from(
        chain,
        index,
        LedgerEntryDraft(
            entry_id=original.entry_id,
            entry_type=original.entry_type,
            payload=payload,
            version_stamp=_required(original.version_stamp),
        ),
    )
    assert verify_chain(forged).is_intact
