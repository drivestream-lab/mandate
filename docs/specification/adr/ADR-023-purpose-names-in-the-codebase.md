# ADR-023: Purpose names in the codebase

- Status: accepted
- Date: 19 Nov 2026 (amended 21 Nov 2026 where noted)
- Source: PL-11 in `mandate-meta/prd/INIT-MANDATE-001-engineering.md`

## Decision

Serial ids (REQ-nn, J-nn, CTR-nn, ER-nn, AD-n, PL-n) belong in the PRDs, tables and docs, never in names in the codebase. Modules, test files, test functions, scripts, fixtures and branches are named for what they do: `tests/journeys/spec_to_release/test_release_merges_only_the_verified_commit.py`, `tests/agents/spec_to_release.py`, `test_board_move_to_done_is_rejected_while_approval_pending`, branch `feature/INIT-MANDATE-001-w3-protected-acceptance-tests`. Ids appear in code only as traceability metadata, `@pytest.mark.req("REQ-63")`, which the coverage check reads to fail the build when a requirement has no test.

## Changing this decision

ADRs are immutable. A change is a new ADR that supersedes this one; update the engineering-ready PRD in the same pull request.
