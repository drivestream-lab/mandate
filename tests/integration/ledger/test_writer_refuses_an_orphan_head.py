"""The writer refuses to extend a head that does not link back to genesis.

Runs against a real Postgres as the runtime role; see tests/integration/conftest.py.
"""

import uuid
from datetime import UTC, datetime

import pytest

from src.business_services.ledger.ledger_append_service import (
    LedgerAppendService,
    LedgerHeadOrphanError,
    build_decision_draft,
)
from src.database.postgres.repository.ledger.ledger_repository import LedgerRepository
from src.engine.ledger.hash_chain import seal_entry
from src.infra_services.postgres_service import PostgresService
from src.models.kernel_models import NamedVersion, VersionStamp
from src.models.ledger_models import DecisionOption, DecisionRecord, RungType

_STAMP = VersionStamp(
    contract="1",
    block_versions=(NamedVersion(name="review", version="2"),),
    skills=(NamedVersion(name="spec-read", version="5"),),
    rules="r1",
    agent_setup="a1",
    policy_revision="p1",
    mandate_release="0.1.0",
)


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


@pytest.mark.req("REQ-55")
async def test_an_orphan_head_stops_the_append_and_leaves_the_ledger_as_it_was(
    postgres: PostgresService,
) -> None:
    repository = LedgerRepository()
    service = LedgerAppendService(postgres, repository)
    await service.append_decision(_decision(), _STAMP)
    # A well-formed entry (its own hash holds) whose link leads to no entry at all.
    orphan = seal_entry(build_decision_draft(_decision(), _STAMP, uuid.uuid4()), "e" * 64)
    async with postgres.transaction() as session:
        await repository.insert(session, orphan)
    assert not (await service.verify()).is_intact

    with pytest.raises(LedgerHeadOrphanError):
        await service.append_decision(_decision(), _STAMP)
    async with postgres.transaction() as session:
        with pytest.raises(LedgerHeadOrphanError):
            await service.append_decision_in(session, _decision(), _STAMP)
    async with postgres.get_session() as session:
        assert len(await repository.read_all(session)) == 2


@pytest.mark.req("REQ-55")
async def test_a_head_that_links_to_genesis_is_extended(postgres: PostgresService) -> None:
    service = LedgerAppendService(postgres, LedgerRepository())
    for _ in range(3):
        await service.append_decision(_decision(), _STAMP)
    assert (await service.verify()).entries_checked == 3
