# Deterministic test agents

Real Paperclip agents on the built-in `process` adapter. Each script here is the scripted step
of one role, calls no model, and builds its output with the models in
`src/models/role_output_models.py`, so a schema change breaks the scripts in the same pull request.

How a run works, as read from the pinned Paperclip build:

- The adapter starts `command` with `args` in `cwd`, inside the Paperclip container, with the
  run's identity in the environment (`PAPERCLIP_API_URL`, `PAPERCLIP_RUN_ID`,
  `PAPERCLIP_API_KEY`). It passes no task.
- Assigning an issue to the agent starts a run. The script asks Paperclip which issue its run
  belongs to and reads the brief from the issue description (JSON).
- The script posts its output as a comment, closes the issue and prints the output on stdout.
  Paperclip keeps stdout in the run's result. A non-zero exit fails the run.
- The output is checked against its model before it is posted. One that fails is not posted:
  it counts as missing.

The container has Python and no packages. The journey harness copies `src/models/` and
`tests/agents/` into the container and installs the pinned pydantic for the container's
platform, then points the agent's `PYTHONPATH` at them.
