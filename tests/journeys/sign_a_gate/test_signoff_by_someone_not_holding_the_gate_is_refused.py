"""Journey: an attested Approve from an identity that does not hold the gate does not pass.

Mandate's own App is the non-holder: it approves with a correct attestation, and the check
still fails and nothing is recorded in the ledger.
"""

import pytest

from src.infra_services.github_app_service import GitHubAppService
from src.infra_services.postgres_service import PostgresService
from src.models.signoff_models import GateDecisionStateType
from tests.journeys.sign_a_gate.conftest import GATE_RULE, SandboxDesk
from tests.journeys.sign_a_gate.support import STAMP, Services


@pytest.mark.req("REQ-40")
async def test_label_ready_and_attested_approve_from_a_non_holder_fails_the_check(
    postgres: PostgresService, github_app: GitHubAppService, sandbox_desk: SandboxDesk
) -> None:
    services = Services(postgres)
    pull = sandbox_desk.open_pull_request("not-the-holder")
    pull.signer_labels()
    pull.signer_marks_ready()
    pull.mandate_approves()

    outcome = await services.check.evaluate_and_post(github_app, pull.ref, GATE_RULE, STAMP)

    assert outcome.state is GateDecisionStateType.FAILURE
    assert "does not hold the gate" in outcome.reason
    posted = pull.gate_decision()
    assert posted is not None and posted.state == "failure"
    assert await services.entry_types() == []
