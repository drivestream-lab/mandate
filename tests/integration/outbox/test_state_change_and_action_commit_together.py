"""A state change, its ledger entry and its outbox message commit in one transaction.

Runs against a real Postgres as the runtime role; see tests/integration/conftest.py for the
settings it needs.
"""

import uuid
from datetime import UTC, datetime

import pytest

from src.business_services.ledger.ledger_append_service import LedgerAppendService
from src.business_services.outbox.outbox_dispatch_service import (
    OutboxDispatchService,
    OutboxTransport,
)
from src.database.postgres.repository.ledger.ledger_repository import LedgerRepository
from src.database.postgres.repository.outbox.outbox_repository import OutboxRepository
from src.database.postgres.schema.runner.work_item_schema import WorkItemSchema
from src.infra_services.postgres_service import PostgresService
from src.models.kernel_models import NamedVersion, VersionStamp
from src.models.ledger_models import DecisionOption, DecisionRecord, RungType
from src.models.outbox_models import NewOutboxMessage
from tests.integration.outbox.helpers import ManualClock, count_rows

_STAMP = VersionStamp(
    contract="1",
    block_versions=(NamedVersion(name="review", version="2"),),
    skills=(NamedVersion(name="spec-read", version="5"),),
    rules="r1",
    agent_setup="a1",
    policy_revision="p1",
    mandate_release="0.1.0",
)


class _NoTransport(OutboxTransport):
    async def deliver(self, message: object) -> None:  # pragma: no cover - never dispatched here
        raise AssertionError("nothing is delivered in these tests")


class _UnitOfWorkFailedError(Exception):
    pass


def _decision() -> DecisionRecord:
    return DecisionRecord(
        actor="nikd10x",
        role="decision owner",
        rung=RungType.L0,
        options_offered=(DecisionOption(option_id="approve", description="Merge it"),),
        choice="approve",
        reasons=("reason",),
        evidence=(),
        target_version="version-1",
        workflow_version="workflow-4",
        model_version="model-7",
        decided_at=datetime(2026, 11, 27, 12, 0, tzinfo=UTC),
    )


async def _unit_of_work(postgres: PostgresService, work_item: uuid.UUID, fail_after: str) -> None:
    ledger = LedgerAppendService(postgres, LedgerRepository())
    outbox = OutboxDispatchService(postgres, OutboxRepository(), _NoTransport(), ManualClock())
    async with postgres.transaction() as session:
        session.add(WorkItemSchema(work_item_id=work_item, state="approved"))
        if fail_after == "state":
            raise _UnitOfWorkFailedError()
        await ledger.append_decision_in(session, _decision(), _STAMP)
        if fail_after == "ledger":
            raise _UnitOfWorkFailedError()
        await outbox.enqueue(
            session,
            NewOutboxMessage(
                work_item_id=str(work_item),
                step="approved",
                destination="paperclip",
                payload={"work_item": str(work_item)},
            ),
        )
        if fail_after == "outbox":
            raise _UnitOfWorkFailedError()


async def _rows(postgres: PostgresService, work_item: uuid.UUID) -> tuple[int, int, int]:
    return (
        await count_rows(postgres, "runner.work_items", f"work_item_id = '{work_item}'"),
        await count_rows(postgres, "ledger.entries"),
        await count_rows(postgres, "outbox.messages"),
    )


@pytest.mark.req("REQ-55")
async def test_a_committed_unit_leaves_state_entry_and_message(postgres: PostgresService) -> None:
    work_item = uuid.uuid4()
    await _unit_of_work(postgres, work_item, fail_after="never")
    assert await _rows(postgres, work_item) == (1, 1, 1)
    ledger = LedgerAppendService(postgres, LedgerRepository())
    assert (await ledger.verify()).is_intact


@pytest.mark.req("REQ-55")
@pytest.mark.parametrize("fail_after", ["state", "ledger", "outbox"])
async def test_a_failed_unit_leaves_none_of_the_three(
    postgres: PostgresService, fail_after: str
) -> None:
    work_item = uuid.uuid4()
    with pytest.raises(_UnitOfWorkFailedError):
        await _unit_of_work(postgres, work_item, fail_after=fail_after)
    assert await _rows(postgres, work_item) == (0, 0, 0)
    # The chain lock and head were released with the rollback: the next unit goes through.
    await _unit_of_work(postgres, uuid.uuid4(), fail_after="never")
    assert await count_rows(postgres, "ledger.entries") == 1
