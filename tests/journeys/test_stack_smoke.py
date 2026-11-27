"""Smoke journey for the ephemeral stack: every service answers and GitHub work stays contained.

No requirement is covered by this file on its own: it proves the stack the journeys run on,
so it carries no requirement marker.
"""

import httpx
from sqlalchemy import URL, text
from sqlalchemy.ext.asyncio import create_async_engine
from temporalio.client import Client

from tests.journeys.journey_support import (
    SANDBOX_REPOS,
    AppCredentials,
    RunNamespace,
    SandboxGitHub,
    StackAddresses,
)


def test_paperclip_answers_its_health_endpoint(journey_stack: StackAddresses) -> None:
    response = httpx.get(f"{journey_stack.paperclip_url}/api/health", timeout=15)

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_postgres_accepts_a_connection(journey_stack: StackAddresses) -> None:
    url = URL.create(
        "postgresql+asyncpg",
        username=journey_stack.postgres_user,
        password=journey_stack.postgres_password,
        host="127.0.0.1",
        port=journey_stack.postgres_port,
        database=journey_stack.postgres_database,
    )
    engine = create_async_engine(url)
    try:
        async with engine.connect() as connection:
            assert (await connection.execute(text("SELECT 1"))).scalar_one() == 1
    finally:
        await engine.dispose()


async def test_temporal_answers(journey_stack: StackAddresses) -> None:
    client = await Client.connect(journey_stack.temporal_address)

    assert await client.service_client.check_health()


def test_test_app_mints_an_installation_token_for_the_sandbox_repos(
    test_app_credentials: AppCredentials,
) -> None:
    token = test_app_credentials.installation_token(SANDBOX_REPOS)

    assert token


def test_run_github_work_is_namespaced_and_removed_at_cleanup(
    sandbox_github: SandboxGitHub, run_namespace: RunNamespace
) -> None:
    svc, meta = SANDBOX_REPOS
    branch = sandbox_github.create_branch(svc, "smoke")
    pull_request = sandbox_github.create_pull_request(svc, branch)
    svc_issue = sandbox_github.create_issue(svc, "smoke")
    meta_issue = sandbox_github.create_issue(meta, "smoke")

    assert branch.startswith(f"{run_namespace.prefix}/")
    assert sandbox_github.branch_exists(svc, branch)
    assert sandbox_github.pull_request_state(svc, pull_request) == "open"
    assert sandbox_github.issue_state(meta, meta_issue) == "open"

    sandbox_github.cleanup()

    assert not sandbox_github.branch_exists(svc, branch)
    assert sandbox_github.pull_request_state(svc, pull_request) == "closed"
    assert sandbox_github.issue_state(svc, svc_issue) == "closed"
    assert sandbox_github.issue_state(meta, meta_issue) == "closed"
