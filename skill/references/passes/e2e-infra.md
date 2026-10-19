# Pass: e2e-infra (step 1.5)

You build the local infrastructure that lets the real system run end to end on a laptop with no external service, and
the first end-to-end tests on top of it. The rule underneath: run the **real** server, fake only what is outside the
system, and make every run start from nothing. Once this exists, every later finding can be reproduced against the
whole stack instead of argued about.

`<skill-dir>` is two folders above this file (the folder that holds `SKILL.md` and `ia.py`).

## Scope

- **HTTP emulators** for each external dependency the inventory found (identity provider, third-party APIs, LLM or
  payment providers, internal services): small servers with **in-memory state**, started on an ephemeral port per test
  run, that speak enough of the real protocol for the system's client code to work unchanged. Each emulator has
  control routes:
  - `POST /__rules`: replaces the list of programmed answers (match on path, method, body substring or regex; first
    rule that matches wins), so a test decides what the dependency replies;
  - `POST /__faults`: replaces the list of programmed failures (status codes, slow answers with a delay, huge bodies,
    redirects, dropped connections), so timeouts and error paths can be tested;
  - `GET /__requests`: the log of what the system sent (method, path, relevant body fields, whether credentials were
    valid), so a test can assert what was or was not called;
  - a reset (route or function) that clears state, rules and faults between tests.
  Credentials accepted by an emulator are fake and documented; an emulator never forwards to the real service.
- **Data stores** with `docker compose` (database, cache, queue broker, search, whatever the system uses), on fixed
  local ports bound to `127.0.0.1`, with throwaway credentials.
- **A disposable database per run**: each test run creates a uniquely named database (random suffix), runs the
  project's real migrations against it, and drops it at the end, even when the run fails. Runs can then go in
  parallel without seeing each other's data.
- **The real server started by the test harness** as a separate process, on a free port, with a **clean environment**:
  only the variables the harness sets (database URL of the per-run database, emulator base URLs, fake keys), never the
  developer's `.env` or shell credentials. The harness waits for readiness, collects the server log, and stops it.
- **E2E tests** through the real interface: HTTP requests with real tokens issued by the identity emulator, and the
  browser with Playwright (or the project's runner) for the frontend against the same stack.
- Documentation for running it, in the tests branch: how to start compose, the command, the variables, what each
  emulator covers and what it does not.

## Out of scope

- Production code changes. The one exception the orchestrator may approve is making an external base URL configurable
  when it is hard-coded (default unchanged); that is a separate commit on its own branch, named in the hand-back, never
  mixed into the tests branch silently.
- Calling real external services. A test against a real provider may exist only as an opt-in, skipped by default,
  documented as non-deterministic.
- Pushing or setting an upstream. Never.

## Inputs

- The run dir, the scope, and the worktree path you own (one worktree per agent, created at the pinned SHA or on the
  repo's `tests_branch` if the unit-tests pass already made it).
- `manifest.json`: `repos[]` (`alias`, `path`, `subdir`, `sha`), `baseline.<ALIAS>.plan` (`test_cmd`, `env`, `deps`,
  `install_cmd`), `baseline.<ALIAS>.tests_branch`, `lang`, `tools` (is `docker` available).
- The baseline-inventory hand-back: external dependencies (and whether their base URL is configurable), data stores,
  how the server starts, which migrations exist.

## Method

1. Pick the minimum set of emulators the main user flows need. For each, read how the system's client calls it (paths,
   auth, payloads) at the pinned SHA and implement only that surface. Prefer the project's language and test runner;
   an existing emulator library already in the project's dependencies is fine, a new one needs the person's approval.
2. Give every emulator the control routes above and a reset. Keep its state JSON-serializable so a scenario can be
   saved and restored.
3. Write `docker-compose.yml` (or extend the project's) for the data stores, ports bound to `127.0.0.1`.
4. Write the harness: create the per-run database, run migrations, start the real server with the clean environment
   pointing at the emulators, wait for readiness, expose a stop that kills the server and drops the database.
5. Write the e2e tests for the main flows (sign in, the core create-read-update path, one integration with an external
   dependency, one failure injected with `/__faults`). Assert on responses and on `GET /__requests`.
6. Make the e2e suite skip cleanly, with a message, when the data stores are not available, so the unit suite keeps
   running anywhere.
7. Run it twice from scratch; both runs green at the base. A flow that fails because the system misbehaves becomes a
   correctness candidate (Output), not a test to bend.
8. Commit on the tests branch with conventional commits (`test(e2e): ...`), staging explicit paths only, no AI
   attribution, no 40-character alphanumeric identifiers in names or fixtures.

## Evidence rules

- Each emulator's surface cites the client code it mirrors (`ALIAS/path` lines at the pinned SHA) in a comment or in
  the documentation.
- "Green" means a saved run: `<run-dir>/outputs/tests-<ALIAS>-e2e.txt`, masked.
- Behaviour you could not emulate (a provider feature with no local equivalent) is listed as not covered, never
  implied.

## Output

1. The tests branch with emulators, compose file, harness, e2e tests and their documentation; its name recorded
   with `python3 <skill-dir>/ia.py set --run <run-dir> baseline.<ALIAS>.tests_branch=<branch>`.
2. Saved e2e output under `outputs/`.
3. A correctness candidate for each flow that fails at the base, prose fields in the run's `lang`:

```bash
python3 <skill-dir>/ia.py finding add --run <run-dir> - <<'EOF'
{"report": "correctness", "category": "<a category from sections.correctness>", "dimension": "distributed",
 "title": "<one technical line>", "verdict": "candidate", "severity": "medium", "confidence": "unverified",
 "source": "e2e-infra",
 "what_happens": "<the flow, the injected condition, what the system did, what the user sees>",
 "evidence": [{"cite": "BACK/src/integrations/client.ts", "from": 52, "to": 60, "note": "no timeout on the outbound call"}]}
EOF
```

4. A hand-back: the command to run everything, emulators and what they cover, flows tested, candidates filed, any
   base-URL change that needs its own branch.

## Done when

- `docker compose up` plus one command runs the e2e suite against the real server, with a per-run database that is
  dropped afterwards, and it is green twice in a row at the base.
- Every emulator has `/__rules`, `/__faults`, `/__requests` and a reset, and no test reaches a real external service
  unless explicitly opted in.
- `baseline.<ALIAS>.tests_branch` names the branch; nothing was pushed.
