You are the lead of the INIT-MANDATE-001 build swarm, for one round only. `make swarm` started you headless; nobody is watching this session. Follow the section "The lead: one round of the swarm" in CLAUDE.md exactly.

1. Rebuild state from the repos and GitHub, never from memory: the WorkManifest (`../mandate-meta/Implementation-Plan-INIT-MANDATE-001.md` section 9, after `git -C ../mandate-meta pull --ff-only`), `docs/specification/as-built/requirements.md`, open and merged PRs with their `mandate/build-verified` statuses and reviews on `drivestream-lab/mandate` and `drivestream-lab/mandate-control-tower`, open `develop-red` issues, and the pinned build-log issue on `drivestream-lab/mandate` (its latest entry says what is waiting on KD).
2. If the latest build-log entry is waiting on KD and nothing KD had to do has changed on GitHub, append a short "still waiting" entry and exit.
3. Otherwise act: merge what is ready, send findings back, start challengers on new heads, start builders for ready tasks (at most 3 builders running), and keep open PRs current.
4. Append exactly one build-log entry for this round, with this round's id `$SWARM_ROUND_ID`, then exit.

Spend so far: `$SWARM_STATE_DIR/spend.tsv` (round id, USD, exit code). Every GitHub write goes through `scripts/swarm/as_role.sh`; never plain `gh` or `git push`.
