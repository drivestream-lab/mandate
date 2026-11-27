"""Idempotency keys are deterministic and distinguish work items and steps."""

import hashlib

import pytest

from src.engine.kernel.idempotency_key import derive_idempotency_key


@pytest.mark.req("REQ-54")
def test_same_inputs_always_give_the_same_key() -> None:
    keys = {derive_idempotency_key("wi-1", "open_pull_request").value for _ in range(50)}
    assert len(keys) == 1


def test_key_is_the_hash_of_the_pinned_encoding() -> None:
    # Pins the encoding: a change to it would break every key already used for a write.
    expected = hashlib.sha256(b'["mandate.idempotency.v1","wi-1","step-a"]').hexdigest()
    assert derive_idempotency_key("wi-1", "step-a").value == expected


def test_different_work_item_or_step_gives_a_different_key() -> None:
    base = derive_idempotency_key("wi-1", "step-a").value
    assert derive_idempotency_key("wi-2", "step-a").value != base
    assert derive_idempotency_key("wi-1", "step-b").value != base


def test_moving_text_across_the_boundary_changes_the_key() -> None:
    assert derive_idempotency_key("a", "bc").value != derive_idempotency_key("ab", "c").value
    assert derive_idempotency_key("a:b", "c").value != derive_idempotency_key("a", "b:c").value


@pytest.mark.parametrize(("work_item_id", "step"), [("", "step"), ("wi", "")])
def test_empty_input_is_rejected(work_item_id: str, step: str) -> None:
    with pytest.raises(ValueError):
        derive_idempotency_key(work_item_id, step)
