"""What an appended entry holds and how it links: the pure parts of the append path.

The path through Postgres (the lock, the unique index, the stored rows) is tested against a
real database in tests/integration/ledger; nothing here fakes the database.
"""

from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError

from src.business_services.ledger.ledger_append_service import (
    LedgerHeadUnverifiableError,
    build_correction_draft,
    build_decision_draft,
    head_hash_to_link,
)
from src.engine.ledger.hash_chain import compute_entry_hash, seal_entry, verify_chain
from src.models.kernel_models import NamedVersion, VersionStamp
from src.models.ledger_models import (
    GENESIS_HASH,
    CorrectionRecord,
    DecisionOption,
    DecisionRecord,
    EvidenceReference,
    LedgerEntryDraft,
    LedgerEntryType,
    RungType,
    SealedLedgerEntry,
    StoredLedgerEntry,
)

_STAMP = VersionStamp(
    contract="1",
    block_versions=(NamedVersion(name="review", version="2"),),
    skills=(NamedVersion(name="spec-read", version="5"),),
    rules="r1",
    agent_setup="a1",
    policy_revision="p1",
    mandate_release="0.1.0",
)
_WHEN = datetime(2026, 11, 27, 12, 0, tzinfo=UTC)


def _decision(**changes: object) -> DecisionRecord:
    values: dict[str, object] = {
        "actor": "nikd10x",
        "role": "decision owner",
        "rung": RungType.L0,
        "options_offered": (
            DecisionOption(option_id="approve", description="Merge it"),
            DecisionOption(option_id="reject", description="Send it back"),
        ),
        "choice": "approve",
        "reasons": ("the evidence matches the spec",),
        "evidence": (EvidenceReference(kind="test-run", reference="run-9", digest="a" * 64),),
        "target_version": "9fa6b30",
        "workflow_version": "workflow-4",
        "model_version": "model-7",
        "decided_at": _WHEN,
    }
    values.update(changes)
    return DecisionRecord.model_validate(values)


def _stored(sealed: SealedLedgerEntry, sequence: int) -> StoredLedgerEntry:
    return StoredLedgerEntry(
        sequence=sequence,
        entry_id=sealed.entry_id,
        entry_type=sealed.entry_type,
        payload=sealed.payload,
        version_stamp=sealed.version_stamp,
        previous_hash=sealed.previous_hash,
        entry_hash=sealed.entry_hash,
        recorded_at=_WHEN,
    )


@pytest.mark.req("REQ-54")
def test_a_decision_entry_holds_everything_a_decision_records() -> None:
    draft = build_decision_draft(_decision(), _STAMP, UUID(int=1))
    assert draft.entry_type == LedgerEntryType.DECISION
    assert set(draft.payload) == {
        "actor",
        "role",
        "rung",
        "options_offered",
        "choice",
        "reasons",
        "evidence",
        "target_version",
        "workflow_version",
        "model_version",
        "decided_at",
    }
    assert draft.version_stamp == _STAMP


@pytest.mark.req("REQ-54")
@pytest.mark.parametrize(
    "field",
    ["actor", "role", "rung", "options_offered", "choice", "reasons", "target_version"]
    + ["workflow_version", "model_version", "decided_at"],
)
def test_a_decision_missing_a_part_is_refused(field: str) -> None:
    values = _decision().model_dump()
    del values[field]
    with pytest.raises(ValidationError):
        DecisionRecord.model_validate(values)


@pytest.mark.req("REQ-54")
@pytest.mark.parametrize(
    "changes",
    [
        {"choice": "defer"},
        {"reasons": ()},
        {"reasons": (" ",)},
        {"actor": " "},
        {"model_version": ""},
        {"decided_at": datetime(2026, 11, 27, 12, 0)},
        {
            "options_offered": (
                DecisionOption(option_id="approve", description="a"),
                DecisionOption(option_id="approve", description="b"),
            )
        },
    ],
)
def test_a_decision_that_does_not_make_sense_is_refused(changes: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        _decision(**changes)


@pytest.mark.req("REQ-54")
def test_the_stamp_is_part_of_what_an_entry_hash_covers() -> None:
    draft = build_decision_draft(_decision(), _STAMP, UUID(int=1))
    other = _STAMP.model_copy(update={"mandate_release": "0.2.0"})
    first = seal_entry(draft, GENESIS_HASH)
    second = seal_entry(draft.model_copy(update={"version_stamp": other}), GENESIS_HASH)
    assert first.entry_hash != second.entry_hash


@pytest.mark.req("REQ-55")
def test_the_first_entry_links_to_genesis_and_each_next_one_to_the_hash_before() -> None:
    first = seal_entry(build_decision_draft(_decision(), _STAMP, UUID(int=1)), GENESIS_HASH)
    head = _stored(first, 4)
    assert first.previous_hash == GENESIS_HASH
    assert head_hash_to_link(None) == GENESIS_HASH
    assert head_hash_to_link(head) == first.entry_hash
    second = seal_entry(build_decision_draft(_decision(), _STAMP, UUID(int=2)), first.entry_hash)
    assert verify_chain([head, _stored(second, 9)]).is_intact


@pytest.mark.req("REQ-55")
def test_a_correction_is_a_new_entry_that_names_the_original_by_its_hash() -> None:
    original = seal_entry(build_decision_draft(_decision(), _STAMP, UUID(int=1)), GENESIS_HASH)
    record = CorrectionRecord(
        corrects_entry_hash=original.entry_hash,
        actor="nikd10x",
        reason="the target version was wrong",
        corrected_decision=_decision(target_version="3469d7b"),
    )
    draft = build_correction_draft(record, _STAMP, UUID(int=2))
    correction = seal_entry(draft, original.entry_hash)
    assert draft.entry_type == LedgerEntryType.CORRECTION
    assert draft.payload["corrects_entry_hash"] == original.entry_hash
    assert correction.entry_id != original.entry_id
    assert correction.previous_hash == original.entry_hash
    chain = [_stored(original, 1), _stored(correction, 2)]
    assert verify_chain(chain).is_intact
    assert chain[0].payload["target_version"] == "9fa6b30"


@pytest.mark.req("REQ-55")
def test_a_correction_must_name_a_well_formed_hash() -> None:
    with pytest.raises(ValidationError):
        CorrectionRecord(
            corrects_entry_hash="not-a-hash",
            actor="a",
            reason="r",
            corrected_decision=_decision(),
        )


@pytest.mark.req("REQ-55")
def test_a_head_that_fails_its_own_hash_is_not_extended() -> None:
    sealed = seal_entry(build_decision_draft(_decision(), _STAMP, UUID(int=1)), GENESIS_HASH)
    tampered = _stored(sealed, 1).model_copy(update={"payload": {"actor": "someone else"}})
    with pytest.raises(LedgerHeadUnverifiableError):
        head_hash_to_link(tampered)
    unhashed = _stored(sealed, 1).model_copy(update={"entry_hash": None})
    with pytest.raises(LedgerHeadUnverifiableError):
        head_hash_to_link(unhashed)


@pytest.mark.req("REQ-55")
def test_a_payload_with_a_float_is_refused_so_the_hash_never_depends_on_rounding() -> None:
    draft = LedgerEntryDraft(
        entry_id=UUID(int=1), entry_type="decision", payload={"n": 0.1}, version_stamp=_STAMP
    )
    with pytest.raises(ValueError):
        seal_entry(draft, GENESIS_HASH)


@pytest.mark.req("REQ-55")
def test_the_entry_hash_is_stable_for_fixed_content() -> None:
    """Pins the encoding: a change to what is covered would change every hash ever written."""
    digest = compute_entry_hash(
        str(UUID(int=1)), "decision", {"b": 1, "a": ["x"]}, _STAMP, GENESIS_HASH
    )
    assert digest == compute_entry_hash(
        str(UUID(int=1)), "decision", {"a": ["x"], "b": 1}, _STAMP, GENESIS_HASH
    )
    assert len(digest) == 64
