# Checklist

The method is what makes the audit credible, not the tools: a pinned base, a measured baseline, red for the right
reason, an explicit filter, deduplication, re-verification of anything severe, plain prose and citations that resolve.
Each step below has what it produces and its acceptance criterion. A step is `done` only when its criterion holds;
otherwise it stays `in_progress` (or `skipped`, with the reason told to the person).

The step names in backticks are the keys of `manifest.json` `steps`, in order.

| # | Step | Produces | Acceptance criterion |
|---|---|---|---|
| 0 | `baseline` | Pinned SHA per repo; inventory (modules, entry points, external dependencies, data stores); suite and coverage measured; tools and workers known; categories and section order chosen | Suite run at the base and its raw output saved. Every later claim is cited against that SHA. |
| 1 | `correctness` | Candidates: bugs, races, distributed-systems flaws, security, supply chain, container; the coverage map | Each candidate has `ALIAS/path` and lines at the base SHA. Every module has a coverage cell for `correctness-general`, `races-distributed` (all topics) and `security`, or the step was closed with `--force-open` and a reason. |
| 1 | `proof` | One local branch per candidate with one commit of tests only | Red for the right reason (below); otherwise discarded with a reason. |
| 1.5 | `tests` | Missing unit tests, e2e tests, local infrastructure, on their own branch | New tests green at the base. A new test that fails becomes a step-1 candidate. |
| 2 | `quality` | Findings from the four lenses, with measured numbers | Each finding cited; each quantitative one carries a tool measurement (or is labelled "not measured with tools"). Every module has a `quality-lenses` coverage cell, or `--force-open` with a reason. |
| - | `contrast` | Another model's verdict on every finding | Read-only. Whatever it refutes is reviewed before the filter. |
| - | `verify` | Re-check of every `high` | Re-verified outside the agent that found it: a fresh subagent that never saw the finder's reasoning, or, on a host without subagents, a different model through a read-only CLI, with test reruns by the orchestrator recorded as such. |
| - | `filter` | The list for the owner team | Explicit rule (below). Totals and shown counts reported. |
| - | `prose` | Owner-team text in `audience` | No internal jargon, no blame, inferences labelled, impact yes and exploitation recipe no; forbidden-terms check passed. |
| - | `hygiene` | Pre-delivery check | Everything under "Hygiene" below holds; `ia.py hygiene` is clean. |
| - | `render` | Two self-contained HTML reports | Every cite resolves at the base SHA (`ia.py cite-check` clean). |

## Step 0 details (`baseline`)

- `ia.py init` refuses a dirty repo and a run dir that git could commit; fix the cause, never work around it.
- `ia.py detect` writes a plan per repo for TypeScript/JavaScript, Python, Java/Kotlin (Maven or Gradle; `framework:
  spring-boot` when the build uses it) and Go. JVM and Go suites run offline, so a missing dependency cache fails the
  suite instead of downloading, and `baseline` says so (`not in the local cache`, never a result): offer `deps=install`
  and ask. It runs the plan's `install_cmd` first: `go mod download` for Go; for Maven and Gradle a first run of the
  suite online, because their resolve-only goals leave jars out, so the suite runs twice. Once the cache is filled,
  set `deps=none` back for later runs. A Go toolchain older than `go.mod` asks for is not a cache problem: the error
  says which version to ask the person for. Counts flagged `warning` (some dependencies missing next to passing
  tests) may be partial: tell the person. Other stacks
  come back `unknown`: work out the suite command yourself, set it with
  `ia.py baseline --run DIR --set ALIAS test_cmd=[...]` (and `junit=[...]` when it writes JUnit XML reports), set
  its modules with `ia.py set --run DIR 'modules.ALIAS=[...]'`, and say in the report that the stack was "not measured
  with tools" (`measured=false`).
- Modules `detect` records, by stack:
  - TypeScript/JavaScript and Python: the folders under `src/modules`, `src/features`, `src/app`, `app`,
    `src/components`, and every other folder of `src/` (of the root without `src/`), plus `src/.` (or `.`) for the
    files sitting directly there.
  - Java/Kotlin: per project (the root and every Maven module or Gradle subproject), the children of the base package
    under `src/main/java|kotlin` (Spring's feature or layer packages), `<base package>/.` for its own files (the
    `@SpringBootApplication` class), and `src/main/resources` (`application.yml` and its profiles). Counts come from
    the JUnit XML reports (`junit` in the plan).
  - Go: `cmd/*`, `internal/*`, `pkg/*`, the other top-level packages, `<container>/.` and `.` for loose Go files;
    never `vendor/` or `testdata/`. Counts come from `go test -json`.
  - When the cut is wrong, replace it: `ia.py set --run DIR 'modules.ALIAS=[...]'`.
- Choose the audit's categories from the system's domains (not a fixed list) and record their order with
  `ia.py set --run DIR 'sections.correctness=[...]' 'sections.quality=[...]'` (see `references/schema.md`).
- A failing baseline is a fact, not a blocker: record it. Later suites are compared against it.

## Coverage map (`correctness`, `quality`)

- `ia.py detect` records `manifest.modules`; `ia.py coverage add` records one cell per module and pass, `found`,
  `nothing` or `n/a` (does not apply, with a `--note` saying why; listed apart in the report); `ia.py coverage status` shows the grid and what is open.
- Required: `correctness` needs `correctness-general`, `races-distributed` and `security` for every module; `quality`
  needs `quality-lenses`. Modules of the `ROOT` alias (config, CI, containers) need only `security` and
  `quality-lenses`; `coverage status` prints `-` for the cells they do not need. Files sitting directly in `src/` (or in
  the alias root when there is no `src/`, or at the repo root for `ROOT`) form the pseudo-module `src/.` (or `.`), so
  bootstrap files such as `src/main.ts` or a `Dockerfile` get their own cell. A `races-distributed` cell also needs `--topics` with every topic number of the pass, and the
  pass hands back the topic × module table behind those calls.
- `ia.py step correctness done` and `quality done` refuse while a cell is open. `--force-open "reason"` closes anyway;
  the reason and the open cells go to `manifest.coverage_waivers` and the reports. `proof done` only warns about
  correctness candidates left.
- Runs from before the map (no `modules` in the manifest) close as they always did.

## Red for the right reason (`proof`)

- Commit 1 holds **only tests**. It must fail on **an assertion about the code at the base SHA that reproduces the
  problem**.
- Not a valid red: a module that does not exist, a broken import, an error in the test's own setup, a badly built mock.
- **Never mock the suspect library:** the test runs the real library with the input the code builds and fakes only
  what lies beyond it (an in-memory server, a closed port).
- Commit 1 passes the stack's type-check too, or `tests[].note` says why. A component with no test runner gets the
  minimal runner config in commit 1, said so in the note; the build never breaks.
- **Never bend a test to force red.** If making it fail means testing something else, discard the candidate.
- Discard when: the red cannot be reproduced with an assertion; the fix needs a refactor. A discard with a good reason
  is a valid result: set `verdict=discarded` and `reason`.
- The branch always stops at the red test: commit 1 holds only tests. The fix is a written proposal in `fix_summary`,
  never code; whoever owns the system applies it.
- Save the raw red output per finding under `outputs/` and point `outputs` at them.
- Every branch is checked pairwise with `ia.py merge-check`; report which pairs conflict.
- Findings no code test can express (configuration, container, CI, supply chain) follow
  `references/verification-rules.md` and carry their confidence (`execution`, `docs`, `unverified`). `unverified`
  ones are told to the person and stay out of the reports.

## Tests details (`tests`)

- Unit tests where coverage is missing, following the red rule in reverse: green at the base, asserting real behaviour.
- E2E with the local infrastructure the system needs: HTTP emulators with in-memory state and control routes, a
  throwaway database per run, `docker compose` for the data stores, the real server started with a clean environment.
- These go on one separate branch, recorded with `ia.py set --run DIR baseline.<ALIAS>.tests_branch=<branch>`.

## Filter (`filter`)

- **Correctness report:** only what reproduces at the base SHA, without refactors and without new functionality. Out:
  refactors, new functionality, CI and tooling, doubtful, closed without code (`exclude`), anything not `confirmed`,
  anything `unverified`.
- **Quality report:** deduplicate first; show everything that survives, grouped by repo and by architecture and code;
  anything the contrast refuted (`contrast.verdict=refute`) or that is `discarded` or `unverified` stays out. "Start
  here" lists the 3 to 5 with the most impact per effort.
- **Duplicates (both reports):** a finding that repeats another one is merged, not discarded: `ia.py finding set
  --run <run-dir> C-56 exclude=duplicate duplicate_of=C-49` (both fields in one call; the target must exist, be in
  the same report and not be a duplicate itself). Keep its verdict and its evidence; move anything it adds to the
  target. The filter hides it and "How it was done" says how many duplicates were merged.
- Nothing is deleted: the data keeps every finding, and the reports say "N of M shown".

## Prose (`prose`)

The owner team did not ask for this audit. Write `audience.title`, `audience.what_happens` and `audience.fix_summary`
in the report language for someone who knows the system but not the audit: what happens and to whom, no internal
names of the audit, no blame, no exploitation steps, inferences marked as such. Run the forbidden-terms check of the
pass before closing.

## Hygiene (`hygiene`)

- Before writing any report: the run dir cannot be committed (outside the audited repos by default).
- Before handing over branches: no 40-character identifiers that secret scanners mistake for secrets; no local tool
  files (`.serena/`, `.idea/`, and similar); action SHAs match the version in their comment; no secret in tests,
  fixtures or saved raw outputs.
- After rendering: no unmasked secret in the reports (`ia.py hygiene` scans `<run>/*.html`), including the value
  behind a secret-named key in a snippet's context lines (`${API_TOKEN:default}`, `password: ...` in a config file).
  Render masks those already; a hit means the HTML was edited or rendered by an older version: render again.
- The same secret-named check (without the bare `key: value` rule, which is only for config files) runs on saved
  outputs, finding files and publish files. `ia.py hygiene --run <run-dir> --fix` masks them in place first (text
  files under `outputs/` and `publish/`, and finding prose) and prints each file it changed, never a value. It never
  touches branches, reports, binary files or files something runs (config, scripts, Dockerfiles, such as the e2e
  infra): amend the branch, render again, move a literal in a runnable file to an environment variable, and decide
  on a binary by hand.

## Branches

- One local branch per correctness finding, without upstream.
- One separate branch for step-1.5 tests that prove no bug.
- Never push.

## Optional publish (`publish: true`)

- One issue per shown finding; draft PRs grouped by changes that can be merged alone, each referencing 1 to 5 issues
  (`Refs #N.`, never `Closes`: the branch only adds the failing test) and naming the files it shares with the others;
  never rename a branch that has an open PR.
- `ia.py publish` (only after `ia.py filter`) writes the bodies and `publish/commands.sh`, runnable as prepared once
  reviewed: `set -eu`, absolute paths, `--repo owner/name` from each repo's remote (a repo without one is skipped with a
  comment), issues first with their numbers captured (and printed: `C-07 -> issue #12`) so each PR body references
  the real ones, every PR created with `--draft` and a body whose first line says the branch only adds a failing test,
  grouped PRs on a local `audit/pr-<n>` branch merged in a throwaway worktree, the push left as a commented line, and
  `--base main` to adjust if the default branch differs. The person runs it; the skill never does.
- Each issue goes to one repo: a finding with a branch, to its branch's repo (its first cite), the same one as its PR;
  one without a branch, to `publish_repo` when set, otherwise to its most cited repo. When it cites several repos and
  went by majority, `commands.sh` says so in a comment: check those before running, and set `publish_repo` with
  `ia.py finding set` where the fix belongs elsewhere.
- Warn the person when they turn it on: on someone else's system, publishing is exactly what the filter tries to keep
  measured and small.
