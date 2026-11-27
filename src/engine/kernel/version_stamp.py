"""Version stamp rules: a canonical encoding, a digest, and a like-with-like comparison."""

import hashlib
import json

from src.models.kernel_models import StampFieldType, VersionStamp


def canonical_stamp_json(stamp: VersionStamp) -> str:
    """Encode a stamp with sorted keys and fixed separators; equal stamps encode equally."""
    return json.dumps(stamp.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))


def stamp_digest(stamp: VersionStamp) -> str:
    """Return the hex SHA-256 of the canonical encoding."""
    return hashlib.sha256(canonical_stamp_json(stamp).encode("utf-8")).hexdigest()


def differing_fields(left: VersionStamp, right: VersionStamp) -> tuple[StampFieldType, ...]:
    """Name the parts of the stamp on which two stamps differ, in a fixed order."""
    return tuple(field for field in StampFieldType if _part(left, field) != _part(right, field))


def is_like_with_like(left: VersionStamp, right: VersionStamp) -> bool:
    """True when two stamps match on every part, so measures from them compare fairly."""
    return not differing_fields(left, right)


def _part(stamp: VersionStamp, field: StampFieldType) -> object:
    match field:
        case StampFieldType.CONTRACT:
            return stamp.contract
        case StampFieldType.BLOCK_VERSIONS:
            return stamp.block_versions
        case StampFieldType.SKILLS:
            return stamp.skills
        case StampFieldType.RULES:
            return stamp.rules
        case StampFieldType.AGENT_SETUP:
            return stamp.agent_setup
        case StampFieldType.POLICY_REVISION:
            return stamp.policy_revision
        case StampFieldType.MANDATE_RELEASE:
            return stamp.mandate_release
