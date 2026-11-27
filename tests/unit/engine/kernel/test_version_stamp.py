"""The version stamp carries every part, rejects gaps, and compares like with like."""

import pytest
from pydantic import ValidationError

from src.engine.kernel.version_stamp import (
    canonical_stamp_json,
    differing_fields,
    is_like_with_like,
    stamp_digest,
)
from src.models.kernel_models import NamedVersion, StampFieldType, VersionStamp


def _stamp(**changes: object) -> VersionStamp:
    base: dict[str, object] = {
        "contract": "1.0.0",
        "block_versions": (NamedVersion(name="review", version="2"),),
        "skills": (NamedVersion(name="spec-read", version="5"),),
        "rules": "rules-7",
        "agent_setup": "agents-3",
        "policy_revision": "policy-9",
        "mandate_release": "0.1.0",
    }
    base.update(changes)
    return VersionStamp.model_validate(base)


@pytest.mark.req("REQ-54")
def test_stamp_carries_every_part() -> None:
    assert set(VersionStamp.model_fields) == {field.value for field in StampFieldType}


@pytest.mark.req("REQ-54")
@pytest.mark.parametrize("field", [f.value for f in StampFieldType])
def test_a_missing_part_is_rejected(field: str) -> None:
    data = _stamp().model_dump()
    del data[field]
    with pytest.raises(ValidationError):
        VersionStamp.model_validate(data)


@pytest.mark.parametrize(
    "field", ["contract", "rules", "agent_setup", "policy_revision", "mandate_release"]
)
def test_an_empty_part_is_rejected(field: str) -> None:
    with pytest.raises(ValidationError):
        _stamp(**{field: ""})


def test_a_repeated_block_name_is_rejected() -> None:
    twice = (NamedVersion(name="a", version="1"), NamedVersion(name="a", version="2"))
    with pytest.raises(ValidationError):
        _stamp(block_versions=twice)


def test_order_of_blocks_does_not_change_the_encoding() -> None:
    a = NamedVersion(name="a", version="1")
    b = NamedVersion(name="b", version="1")
    first = _stamp(block_versions=(a, b))
    second = _stamp(block_versions=(b, a))
    assert canonical_stamp_json(first) == canonical_stamp_json(second)
    assert stamp_digest(first) == stamp_digest(second)


def test_json_round_trip_keeps_the_stamp() -> None:
    stamp = _stamp()
    assert VersionStamp.model_validate_json(stamp.model_dump_json()) == stamp


def test_digest_changes_when_any_part_changes() -> None:
    base = stamp_digest(_stamp())
    assert stamp_digest(_stamp(policy_revision="policy-10")) != base
    assert stamp_digest(_stamp(skills=(NamedVersion(name="spec-read", version="6"),))) != base


def test_differing_fields_are_named_in_a_fixed_order() -> None:
    changed = _stamp(mandate_release="0.2.0", contract="2.0.0")
    assert differing_fields(_stamp(), changed) == (
        StampFieldType.CONTRACT,
        StampFieldType.MANDATE_RELEASE,
    )
    assert not is_like_with_like(_stamp(), changed)
    assert is_like_with_like(_stamp(), _stamp())
