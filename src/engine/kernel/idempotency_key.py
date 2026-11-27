"""Idempotency keys: derived from the work item and the step, so a repeat has one effect."""

import hashlib
import json

from src.models.kernel_models import IdempotencyKey

_KEY_SCHEME = "mandate.idempotency.v1"


def derive_idempotency_key(work_item_id: str, step: str) -> IdempotencyKey:
    """Hash a canonical encoding of the work item and step; the same inputs give the same key.

    The encoding is a JSON array with fixed separators, so no pair of different inputs can
    encode to the same bytes (a delimiter inside a value cannot shift the boundary).
    """
    if not work_item_id or not step:
        raise ValueError("work item and step must both be non-empty")
    canonical = json.dumps(
        [_KEY_SCHEME, work_item_id, step], separators=(",", ":"), ensure_ascii=True
    )
    return IdempotencyKey(value=hashlib.sha256(canonical.encode("ascii")).hexdigest())
