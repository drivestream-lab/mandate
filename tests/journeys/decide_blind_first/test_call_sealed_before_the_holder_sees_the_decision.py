"""Journey: the deciding role's call is sealed before the brief is posted, never shown on the
pull request, and revealed only after the holder's signoff is recorded.

Runs on the journey stack: a real Postgres (a throwaway migrated database on the stack's
server), the pinned Paperclip with a scripted deciding role, and a real pull request in the
sandbox repo. The brief is read back from GitHub (body, comments, reviews and review comments)
and searched for any part of the call.
"""

import os
import secrets
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

from src.business_services.gates.gate_opening_service import GateOpeningService
from src.business_services.gates.sealed_call_service import (
    SealedCallMismatchError,
    SealedCallService,
    SignoffNotRecordedError,
)
from src.business_services.ledger.ledger_append_service import LedgerAppendService
from src.configs.base_settings import BaseSettings
from src.database.postgres.connection_manager import PostgresConnectionManager
from src.database.postgres.repository.gates.gate_repository import GateRepository
from src.database.postgres.repository.ledger.ledger_repository import LedgerRepository
from src.infra_services.postgres_service import PostgresService
from src.models.gate_models import (
    BriefOption,
    GateBrief,
    GateClassType,
    OpenedGate,
    PullRequestRef,
    RoleBrief,
)
from src.models.kernel_models import NamedVersion, VersionStamp
from src.models.ledger_models import (
    DecisionOption,
    DecisionRecord,
    EvidenceReference,
    LedgerEntryType,
    RungType,
    SealedCallRecord,
)
from tests.contract.paperclip.conftest import mandate_identity, paperclip
from tests.journeys.journey_support import SANDBOX_REPOS, AppCredentials, SandboxGitHub
from tests.journeys.journey_support import StackAddresses
from tests.journeys.test_agents.conftest import AgentDesk, agent_host, desk

__all__ = ["agent_host", "desk", "mandate_identity", "paperclip"]

_ROOT = Path(__file__).resolve().parents[3]
_REPO = SANDBOX_REPOS[1]
_OWNER = "drivestream-lab"
_STAMP = VersionStamp(
    contract="1",
    block_versions=(NamedVersion(name="gate", version="1"),),
    skills=(NamedVersion(name="brief", version="1"),),
    rules="r1",
    agent_setup="a1",
    policy_revision="p1",
    mandate_release="0.1.0",
)
_NOTE = f"role-note-{secrets.token_hex(6)}"


@pytest.fixture(name="database")
def throwaway_database(
    journey_stack: StackAddresses, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Iterator[str]:
    """A migrated database on the stack's Postgres, with mandate_app able to log in."""
    name = f"gate_{uuid.uuid4().hex[:10]}"
    app_password = secrets.token_hex(12)
    url = URL.create(
        "postgresql+psycopg2",
        username=journey_stack.postgres_user,
        password=journey_stack.postgres_password,
        host="127.0.0.1",
        port=journey_stack.postgres_port,
        database="postgres",
    )
    engine = create_engine(url, isolation_level="AUTOCOMMIT")
    with engine.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    admin_file = tmp_path / "admin-password"
    admin_file.write_text(journey_stack.postgres_password)
    app_file = tmp_path / "app-password"
    app_file.write_text(app_password)
    migrate_env = {
        **os.environ,
        "POSTGRES_HOST": "127.0.0.1",
        "POSTGRES_PORT": str(journey_stack.postgres_port),
        "POSTGRES_USER": journey_stack.postgres_user,
        "POSTGRES_PASSWORD_FILE": str(admin_file),
        "POSTGRES_MIGRATION_USER": journey_stack.postgres_user,
        "POSTGRES_MIGRATION_PASSWORD_FILE": str(admin_file),
        "POSTGRES_DB": name,
    }
    subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(_ROOT / "postgres_migrations" / "alembic.ini"),
         "upgrade", "head"],
        cwd=_ROOT, env=migrate_env, check=True, capture_output=True,
    )  # fmt: skip
    with engine.connect() as connection:
        connection.execute(text(f"ALTER ROLE mandate_app LOGIN PASSWORD '{app_password}'"))
    monkeypatch.setenv("POSTGRES_HOST", "127.0.0.1")
    monkeypatch.setenv("POSTGRES_PORT", str(journey_stack.postgres_port))
    monkeypatch.setenv("POSTGRES_USER", "mandate_app")
    monkeypatch.setenv("POSTGRES_PASSWORD_FILE", str(app_file))
    monkeypatch.setenv("POSTGRES_DB", name)
    BaseSettings.clear_instances()
    yield name
    BaseSettings.clear_instances()
    with engine.connect() as connection:
        connection.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
    engine.dispose()


@pytest_asyncio.fixture(name="postgres")
async def app_postgres(database: str) -> AsyncIterator[PostgresService]:
    service = PostgresService(PostgresConnectionManager())
    await service.initialize()
    yield service
    await service.close()


class _Head(BaseModel):
    model_config = ConfigDict(extra="ignore")
    sha: str


class _Pull(BaseModel):
    model_config = ConfigDict(extra="ignore")
    body: str | None
    head: _Head


class _Text(BaseModel):
    model_config = ConfigDict(extra="ignore")
    body: str | None = None


class _GitHubPullRequest:
    """A pull request in the sandbox repo: posts a brief on it and reads everything back."""

    def __init__(self, credentials: AppCredentials, number: int) -> None:
        self._credentials = credentials
        self.ref = PullRequestRef(repo=_REPO, number=number)

    def _client(self) -> httpx.Client:
        token = self._credentials.installation_token(SANDBOX_REPOS)
        return httpx.Client(
            base_url=f"https://api.github.com/repos/{_OWNER}/{_REPO}",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=30,
        )

    def head_sha(self) -> str:
        with self._client() as client:
            pull = client.get(f"/pulls/{self.ref.number}").raise_for_status()
        return _Pull.model_validate_json(pull.content).head.sha

    async def post_brief(self, pull_request: PullRequestRef, body: str) -> None:
        assert pull_request == self.ref
        with self._client() as client:
            client.post(
                f"/issues/{self.ref.number}/comments", json={"body": body}
            ).raise_for_status()

    def everything_on_it(self) -> str:
        """The body, every comment, every review and every review comment, as one text."""
        number = self.ref.number
        parts: list[str] = []
        with self._client() as client:
            pull = client.get(f"/pulls/{number}").raise_for_status()
            parts.append(_Pull.model_validate_json(pull.content).body or "")
            for path in (f"/issues/{number}/comments", f"/pulls/{number}/reviews",
                         f"/pulls/{number}/comments"):  # fmt: skip
                listing = client.get(path, params={"per_page": 100}).raise_for_status()
                parts += [_Text.model_validate(item).body or "" for item in listing.json()]
        return "\n".join(parts)


class _Observed(BaseModel):
    ledger_types_at_post: tuple[str, ...] = Field(default=())


class _PosterThatRecordsTheLedger:
    """Posts for real, and notes which ledger entries existed at the moment of posting."""

    def __init__(self, pull: _GitHubPullRequest, postgres: PostgresService) -> None:
        self._pull = pull
        self._postgres = postgres
        self.observed = _Observed()

    async def post_brief(self, pull_request: PullRequestRef, body: str) -> None:
        async with self._postgres.get_session() as session:
            entries = await LedgerRepository().read_all(session)
        self.observed = _Observed(ledger_types_at_post=tuple(e.entry_type for e in entries))
        await self._pull.post_brief(pull_request, body)


_AGENTS: dict[str, str] = {}


def _deciding_agent(desk_: AgentDesk) -> str:
    """One scripted deciding role for the whole run: hiring one per test starves Paperclip."""
    company = desk_.identity.company_id
    if company not in _AGENTS:
        _AGENTS[company] = desk_.hire("Deciding role", "deciding_role.py")
    return _AGENTS[company]


class _ScriptedRole:
    """Asks the scripted deciding role on Paperclip, and counts how often it was asked."""

    def __init__(self, desk_: AgentDesk, fault: bool = False, off_list: bool = False) -> None:
        self._desk = desk_
        self._fault = fault
        self._off_list = off_list
        self.shown: list[RoleBrief] = []
        self._agent = _deciding_agent(desk_)
        self.asked = 0

    async def request_call(self, brief: RoleBrief) -> str | None:
        self.asked += 1
        self.shown.append(brief)
        body: dict[str, object] = {
            "options": (
                ["banana"]
                if self._off_list
                else [option.option_id for option in brief.options][::-1]
            ),
            "evidence": [_NOTE],
        }
        if self._fault:
            body["fault"] = "omit_evidence"
        issue = self._desk.assign(self._agent, f"Decide {self.asked}", body)
        return self._desk.first_finished_run(self._agent, issue).stdout or None


def _brief(gate_class: GateClassType, head_sha: str) -> GateBrief:
    return GateBrief(
        gate_class=gate_class,
        title="Gate: add a retry to delivery",
        what_is_decided="Whether delivery retries failed sends",
        options=(
            BriefOption(option_id="ship", description="Add the retry", impact="Fewer lost sends"),
            BriefOption(option_id="hold", description="Leave it", impact="Sends can be lost"),
        ),
        recommendation="ship",
        recommendation_reason="Lost sends cost more than a retry",
        head_sha=head_sha,
        evidence=(EvidenceReference(kind="ci", reference="run 12", digest="b" * 64),),
        after_signoff="The retry merges and the next wave starts",
    )


def _holder_decision(head_sha: str) -> DecisionRecord:
    return DecisionRecord(
        actor="holder",
        role="gate holder",
        rung=RungType.L0,
        options_offered=(
            DecisionOption(option_id="ship", description="Add the retry"),
            DecisionOption(option_id="hold", description="Leave it"),
        ),
        choice="ship",
        reasons=("agreed",),
        evidence=(),
        target_version=head_sha,
        workflow_version="w1",
        model_version="human",
        decided_at=datetime(2026, 11, 27, 12, 0, tzinfo=UTC),
    )


def _pull_request(
    sandbox_github: SandboxGitHub, credentials: AppCredentials, name: str
) -> _GitHubPullRequest:
    branch = sandbox_github.create_branch(_REPO, name)
    return _GitHubPullRequest(credentials, sandbox_github.create_pull_request(_REPO, branch))


async def _sealed_record(postgres: PostgresService, opened: OpenedGate) -> SealedCallRecord:
    async with postgres.get_session() as session:
        stored = await LedgerRepository().get_by_hash(session, opened.sealed.sealed_entry_hash)
    assert stored is not None
    return SealedCallRecord.model_validate(stored.payload)


async def _types(postgres: PostgresService) -> list[str]:
    async with postgres.get_session() as session:
        return [e.entry_type for e in await LedgerRepository().read_all(session)]


def _services(postgres: PostgresService) -> tuple[GateOpeningService, SealedCallService]:
    ledger_repository = LedgerRepository()
    sealed = SealedCallService(
        postgres, LedgerAppendService(postgres, ledger_repository), ledger_repository
    )
    return GateOpeningService(postgres, GateRepository(), sealed), sealed


@pytest.mark.req("REQ-39")
@pytest.mark.req("REQ-103")
@pytest.mark.req("REQ-118")
async def test_call_is_sealed_hidden_from_the_pull_request_and_revealed_after_signoff(
    postgres: PostgresService,
    desk: AgentDesk,
    sandbox_github: SandboxGitHub,
    test_app_credentials: AppCredentials,
) -> None:
    pull = _pull_request(sandbox_github, test_app_credentials, "intent-gate")
    head = pull.head_sha()
    opening, sealed_calls = _services(postgres)
    role = _ScriptedRole(desk)
    poster = _PosterThatRecordsTheLedger(pull, postgres)

    opened = await opening.open_gate(
        uuid.uuid4(), _brief(GateClassType.INTENT, head), pull.ref, role, poster, _STAMP
    )

    # The call was hashed into the ledger before the brief was posted.
    assert poster.observed.ledger_types_at_post == (LedgerEntryType.SEALED_CALL,)
    record = await _sealed_record(postgres, opened)
    call, nonce = record.call, record.nonce
    assert call is not None and call.option == "hold" and call.evidence_cited == (_NOTE,)
    assert nonce is not None
    # The role was never shown the author's recommendation or its reason.
    shown = role.shown[0].model_dump_json()
    assert "Lost sends cost more than a retry" not in shown
    assert "recommend" not in shown
    # The brief is on the pull request, and nothing on the pull request holds the call.
    on_github = pull.everything_on_it()
    for part in (head, "Whether delivery retries failed sends", "Impact: Fewer lost sends",
                 "Recommended: **ship**", "The retry merges and the next wave starts"):  # fmt: skip
        assert part in on_github
    for secret in (call.reasons[0], _NOTE, nonce, opened.sealed.sealed_entry_hash,
                   "Deciding role"):  # fmt: skip
        assert secret not in on_github
    assert record.call_digest is not None and record.call_digest not in on_github

    # Reveal is refused until the signoff is recorded, and the ledger is untouched.
    with pytest.raises(SignoffNotRecordedError):
        await sealed_calls.reveal(opened.gate_id, signoff_recorded=False, stamp=_STAMP)
    assert await _types(postgres) == [LedgerEntryType.SEALED_CALL]
    # The holder signs off (their decision is recorded), and then the reveal is allowed.
    await LedgerAppendService(postgres, LedgerRepository()).append_decision(
        _holder_decision(head), _STAMP
    )
    # A fresh service instance, holding nothing in memory, reveals from the ledger alone.
    _, restarted = _services(postgres)
    await restarted.reveal(opened.gate_id, signoff_recorded=True, stamp=_STAMP)
    assert await _types(postgres) == [
        LedgerEntryType.SEALED_CALL,
        LedgerEntryType.DECISION,
        LedgerEntryType.CALL_REVEAL,
    ]
    assert (await LedgerAppendService(postgres, LedgerRepository()).verify()).is_intact


@pytest.mark.req("REQ-103")
async def test_verification_gate_shows_the_recommendation_with_its_evidence(
    postgres: PostgresService,
    desk: AgentDesk,
    sandbox_github: SandboxGitHub,
    test_app_credentials: AppCredentials,
) -> None:
    pull = _pull_request(sandbox_github, test_app_credentials, "verification-gate")
    head = pull.head_sha()
    opening, _ = _services(postgres)

    opened = await opening.open_gate(
        uuid.uuid4(),
        _brief(GateClassType.VERIFICATION, head),
        pull.ref,
        _ScriptedRole(desk),
        _PosterThatRecordsTheLedger(pull, postgres),
        _STAMP,
    )

    call = (await _sealed_record(postgres, opened)).call
    assert call is not None
    on_github = pull.everything_on_it()
    assert "Deciding role's recommendation" in on_github
    assert call.reasons[0] in on_github
    assert _NOTE in on_github


@pytest.mark.req("REQ-118")
async def test_call_that_never_fits_its_schema_is_asked_for_once_more_then_counts_as_none(
    postgres: PostgresService,
    desk: AgentDesk,
    sandbox_github: SandboxGitHub,
    test_app_credentials: AppCredentials,
) -> None:
    pull = _pull_request(sandbox_github, test_app_credentials, "no-call-gate")
    head = pull.head_sha()
    opening, sealed_calls = _services(postgres)
    role = _ScriptedRole(desk, fault=True)

    opened = await opening.open_gate(
        uuid.uuid4(), _brief(GateClassType.DESIGN, head), pull.ref, role,
        _PosterThatRecordsTheLedger(pull, postgres), _STAMP,
    )  # fmt: skip

    assert role.asked == 2
    record = await _sealed_record(postgres, opened)
    assert record.call is None and record.call_digest is None
    with pytest.raises(SealedCallMismatchError):
        await sealed_calls.reveal(opened.gate_id, signoff_recorded=True, stamp=_STAMP)


@pytest.mark.req("REQ-118")
async def test_call_for_an_option_not_offered_is_asked_for_once_more_then_counts_as_none(
    postgres: PostgresService,
    desk: AgentDesk,
    sandbox_github: SandboxGitHub,
    test_app_credentials: AppCredentials,
) -> None:
    pull = _pull_request(sandbox_github, test_app_credentials, "off-list-gate")
    opening, _ = _services(postgres)
    role = _ScriptedRole(desk, off_list=True)

    opened = await opening.open_gate(
        uuid.uuid4(), _brief(GateClassType.INTENT, pull.head_sha()), pull.ref, role,
        _PosterThatRecordsTheLedger(pull, postgres), _STAMP,
    )  # fmt: skip

    assert role.asked == 2
    assert (await _sealed_record(postgres, opened)).call is None
