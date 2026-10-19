# Pass: baseline-inventory (step 0)

You map the system before anyone looks for problems in it. Everything later in the audit (which modules each subagent
gets, which categories the reports have, which races are even possible) depends on this map being right, so measure
rather than guess.

`<skill-dir>` is two folders above this file (the folder that holds `SKILL.md` and `ia.py`). Call the CLI as
`python3 <skill-dir>/ia.py ...`.

## Scope

- Every repo of the run, at its pinned SHA.
- Modules and their size; entry points (HTTP servers, CLIs, workers, scheduled jobs, frontends); external dependencies
  (third-party APIs, identity providers, LLM or payment providers, message brokers); data stores (databases, caches,
  queues, object stores, search indexes) and who creates their schema.
- How each process starts: what the start command runs, what it does before it listens (migrations, seeds, warm-ups),
  which background workers exist and what starts them.
- The test suite as `ia.py baseline` measured it, and the test infrastructure that exists (fixtures, factories,
  containers, emulators).
- The categories for the two reports and the strengths worth saying.

## Out of scope

- Looking for bugs, races or quality problems. Note a suspicion in one line for the orchestrator; do not file findings.
- Editing anything in the audited repos. This pass is read-only.
- Installing tools. `ia.py detect` already asked the person; use what is on the PATH.

## Inputs

- The run dir (given by the orchestrator).
- `manifest.json`: `repos[]` (`alias`, `path`, `subdir`, `sha`), `lang`, `tools`, `workers`,
  `baseline.<ALIAS>.plan` (`stack`, `test_cmd`, `coverage_cmd`, `measure`, `measured`) and
  `baseline.<ALIAS>.result` (`passed`, `failed`, `total`, `coverage`, `output`).
- The raw baseline output under `outputs/baseline-<ALIAS>.txt`.

## Method

1. Read the code at the pinned SHA only: `git -C <path> show <sha>:<file>`, `git -C <path> ls-tree -r --name-only <sha>`,
   or a worktree the orchestrator created at that SHA. Never the live checkout, which may have moved.
2. List the modules under each alias root with their line counts (`git ls-tree` plus `wc -l` on the files, or a
   language tool). Name the five largest files.
3. Find every entry point: package scripts, `Dockerfile` `CMD`/`ENTRYPOINT`, compose files, Procfiles, deployment
   manifests, `main` functions. For each, write what process it starts and what that process does before serving.
4. Find every external dependency from configuration and environment variable reads (`process.env`, `os.environ`,
   settings classes, `.env.example`) and from HTTP client construction. Note which ones have a configurable base URL:
   step 1.5 needs that to point them at emulators.
5. Find every data store and how its schema is created: migrations, ORM sync, seed scripts, DDL run at startup. Note
   when more than one path changes the schema.
6. Find queues, workers and schedulers: who enqueues, who consumes, and which command starts the consumer. Note a
   worker that no command starts.
7. Read the baseline result. If the stack was `unknown`, work out the suite command, set it with
   `python3 <skill-dir>/ia.py baseline --run <run-dir> --set ALIAS 'test_cmd=["..."]'`, run
   `python3 <skill-dir>/ia.py baseline --run <run-dir> --alias ALIAS`, and say the numbers were "not measured with
   tools" when no runner summary could be parsed.
8. Propose the categories: group the system by its own domains (the things its users do), not by a fixed list. Order
   them by risk for the correctness report and by size for the quality report.
9. Note real strengths with a citation each (a good test harness, a clean boundary, strict compiler settings).

## Evidence rules

- Every statement about the system cites `ALIAS/path` and lines at the pinned SHA. `ALIAS/path` is relative to the
  alias root (the repo top level joined with its `subdir`).
- Counts come from a command you ran; write the command next to the number. A number you did not measure is labelled
  "inference".
- "There is no X" needs the search you ran and where you looked, including CI and configuration outside the code
  (`references/verification-rules.md`, rule 1). If something lives outside the repository, write "not visible from
  this repository".

## Output

This pass adds no findings. It produces:

1. `sections`, recorded with `ia.py set` (never by editing `manifest.json`):

```bash
python3 <skill-dir>/ia.py set --run <run-dir> 'sections.correctness=["<domain>","<domain>"]' \
  'sections.quality=["<domain>","<domain>"]'
```

2. `strengths`: a list of short strings in the run's `lang`, each ending with its cite, recorded the same way:
   `ia.py set --run <run-dir> 'strengths=["Every route validates its input with a schema (BACK/src/routes/orders.ts:12-30)"]'`.
3. Then `python3 <skill-dir>/ia.py status --run <run-dir>` to confirm the run still loads.
4. A hand-back to the orchestrator with: the module map (alias, module, files, lines), entry points and their startup
   work, external dependencies (configurable base URL or not), data stores and schema paths, queues and their
   starters, the measured baseline, and a proposed split of steps 1 and 2 into subagent scopes small enough to read in
   full.

## Done when

- Every repo has a module map, entry points, dependencies and data stores with cites at the pinned SHA.
- `sections` and `strengths` are in `manifest.json` and `ia.py status` loads it.
- The baseline is recorded for every repo (measured, or labelled "not measured with tools").
- The orchestrator has a proposed split of the later steps by module.
