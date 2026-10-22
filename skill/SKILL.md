---
name: inherited-audit
description: Use when you inherit a system (frontend and backend) you did not build and must audit it before building on it: bugs, race conditions and distributed-systems flaws proven by failing tests, missing unit and e2e tests with local infrastructure, and code-quality and architecture findings, delivered as two self-contained HTML reports for the owning team. Resumable across sessions and hosts; runs on Claude Code and Cursor. Not for reviewing a single diff (use /code-review).
compatibility: python3 3.9+ (standard library only) and git 2.38+. Optional workers are listed in references/workers.md.
---

# inherited-audit

You direct an audit of a system someone else built (one or more repos, frontend and backend) and deliver two
self-contained HTML reports for the team that owns it:

1. **Correctness:** bugs, races, distributed-systems flaws, security, supply chain and container hardening, each code
   finding proven by a test that fails at the pinned base.
2. **Quality and architecture:** code, design, architecture, resilience and documentation findings, each with a
   suggestion and, when quantitative, a tool measurement.

Along the way you add the missing unit and e2e tests (step 1.5) on their own branch.

You are the site manager, not the bricklayer: this skill holds the checklist, the order, the acceptance criteria, the
finding format and the render. Workers do the work: the host's own skills, popular external ones, or this skill's pass
prompts where nothing good exists. The `ia` CLI does the mechanical parts and never calls a model.

## When to use, and when not

Use it when someone hands over a system to build on and wants to know what they are standing on: "audit this repo
before we start", "what is broken in this inherited backend", "find races and missing tests in this system".

Not for:

- Reviewing a single diff or a colleague's PR: use `/code-review` (Claude Code) or `/review-bugbot` (Cursor).
- UI or accessibility audits.
- Fixing the quality findings: the quality report only suggests.

## Ground rules (never broken)

- **Never push**, never open PRs, never create issues, never run the `gh` commands that `ia.py publish` prepares. The
  person publishes. Read-only lookups are fine and expected (a `gh api` GET, a registry or release page read) to verify
  external references.
- **Never install anything without asking.** Missing workers are asked about once, in step 0, and never again.
- **Never write the reports where they can be committed.** They carry security findings; `ia.py init` and
  `ia.py hygiene` enforce it.
- **No claim without evidence.** Every finding cites `ALIAS/path` and lines at the pinned base; a claim you did not
  run is a guess (`references/verification-rules.md`).
- **One worktree per parallel agent.** Two subagents never share a working tree; each gets its own git worktree of the
  audited repo, created from the pinned SHA or the finding's branch, and removed when it is done.
- **The owner team is not the enemy.** No blame, no internal jargon, no exploitation recipes, and a report short enough
  to read.

## Options

| Option | Default | Effect |
|---|---|---|
| `publish` | `false` | With `true`, at the end `ia.py publish` writes issue and PR bodies and the exact `gh` commands. It never runs them. |

Ask only if the person did not say. It maps to `ia.py init --publish`. The skill never applies a fix: every confirmed
correctness finding stops at a branch with the red test (commit 1, tests only) and the written proposal in
`fix_summary`. The old fix flag of `init` is gone (`init` refuses it); a manifest with `options.fix: true` still loads, warns
once and behaves as `false`. When `publish` is on, warn once: on someone else's system, publishing is exactly what the owner-team filter tries to keep small; the person
decides what to run.

## The CLI and where it lives

`<skill-dir>` is the folder that contains this SKILL.md (the path you loaded it from, for example
`~/.claude/skills/inherited-audit`). Always call the CLI by that absolute path, from any working directory:

```bash
python3 <skill-dir>/ia.py status --run <run-dir>
```

Every command of the run takes `--run <run-dir>`; `init` creates it. Exit codes: 0 ok, 1 the command found problems, 2 usage error, 3 an external tool failed or is missing, 4 ia itself failed.
On 1, read the problems it printed and fix them; on 2, read the usage; on 3, tell the person which tool failed; on 4,
do not work around it: show the person the one-line error (rerun with `IA_DEBUG=1` for the traceback). 128+N means a
signal N stopped `ia` (143 SIGTERM, 129 SIGHUP, 130 Ctrl-C) after it cleaned up; run the command again. A SIGKILL
cannot be caught: after one, run `git worktree prune` in the audited repo.
Subagents may call `finding add|set`, `coverage add`, `set`, `step`, `detect`, `filter` and `baseline` on one run at
the same time: their manifest and finding writes take a lock on the run dir (`.ia.lock`). `render` and `publish` are
for the orchestrator alone, at the end.

## Always start here

1. If a run already exists (the person names it, or you find `<parent-of-first-repo>/<system>-inherited-audit/<date>/`
   with a `manifest.json`), run `python3 <skill-dir>/ia.py status --run <run-dir>` and resume at the first step that
   is not `done` or `skipped`, on whichever host you are. Read `manifest.json` `options` and `host` instead of asking
   again. If the host changed, record it and refresh the worker table, so the new host's rows apply from here on:
   `python3 <skill-dir>/ia.py set --run <run-dir> host=<cursor|claude-code> && python3 <skill-dir>/ia.py detect --run <run-dir>`
   (`detect` keeps every plan key edited with `baseline --set`).
2. Otherwise detect the host (next section) and create the run:

```bash
python3 <skill-dir>/ia.py init --system <name> --repo BACK=/abs/backend --repo FRONT=/abs/frontend:web \
  --host <claude-code|cursor|unknown> [--publish] [--lang es] [--out <dir>]
```

`--repo ALIAS=PATH[:SUBDIR]` is repeatable; the alias is what every cite starts with. `init` pins `HEAD` of each repo,
refuses dirty repos (commit or stash first, with the person's agreement) and refuses an output dir git could commit.
Reports default to `es`; pass `--lang` if the owner team reads another language. When every alias of a repo has a
subdir (a monorepo split by folders), `init` also adds the alias `ROOT` (`ROOT2`... if taken) for the repo root and prints
it: cite root-level files as `ROOT/Dockerfile` or `ROOT/.github/workflows/ci.yml`.

A cite can point into history with `ALIAS/path@<commit>` (7-40 hex; `cite-check` requires it to be an ancestor of the
base). **Secrets present only in git history** are filed as `dimension: security`, `confidence: execution`,
`measurement.tool: gitleaks ...`, `outputs.suite` naming the redacted output saved under `outputs/`, an evidence cite
with `@commit`, no branch, and **the value is never written** (full example in `references/schema.md`); the report
shows path and commit and no snippet for security and supply-chain cites.

## Host detection

Measured on 2026-10-18 (the shell environment each host gives to commands):

- Cursor's agent sets `CURSOR_AGENT` (and `CURSOR_INVOKED_AS`) and may **also** inherit `CLAUDECODE` from a parent
  process, so check it first.
- Claude Code sets `CLAUDECODE=1` (and `CLAUDE_CODE_ENTRYPOINT`).

Rule: if `CURSOR_AGENT` is set, the host is `cursor`; else if `CLAUDECODE` is set, it is `claude-code`; else ask the
person once and use `unknown` if they do not know. Pass the result to `ia.py init` with `--host`.

```bash
if [ -n "$CURSOR_AGENT" ]; then echo cursor; elif [ -n "$CLAUDECODE" ]; then echo claude-code; else echo unknown; fi
```

## Handing a pass to a subagent

The skill does not depend on named subagents. For every pass:

- Launch a **generic** subagent. Claude Code: the general-purpose agent type. Cursor: analysis passes run in a terminal
  through the read-only `agent -p` invocation shown in the contrast row of `references/workers.md` (same command,
  with the pass's prompt and model); writing passes run as a new agent in their own worktree.
- Its prompt is three things: the absolute path of the pass file (`<skill-dir>/references/passes/<name>.md`), the run
  dir, and the model to use. Add the scope (which alias, which modules, which finding ids) and the worktree path it
  owns. Do not paste the pass text; the subagent reads it.
- **Analysis passes are read-only** (correctness-general, races-distributed, security, supply-chain-container,
  quality-lenses, contrast, verify-high): they read code and add findings with `ia.py finding add`, but never edit
  files or branches of the repos. verify-high (and supply-chain-container, to scan or build) may create a throwaway
  worktree, which only adds git metadata, and removes it when done. Only the proof, unit-tests and e2e-infra passes
  write, and only on their own branch in their own worktree.
- Split big systems by module so each subagent has a scope it can read in full; run independent ones in parallel,
  each in its own worktree.
- When a subagent returns, check its findings with `ia.py finding list --run <run-dir>` rather than trusting its
  summary.

When a pass prints JSON blocks instead of writing (a read-only host mode, such as Cursor's agent CLI in ask mode), you
apply them. Save each finding block to its own file and run `ia.py finding add --run <run-dir> <file>`. A contrast
line `{"id": "C-07", "contrast": {...}}` becomes one call:
`ia.py finding set --run <run-dir> C-07 contrast.model=<model> contrast.same_family=<true|false>
contrast.verdict=<agree|refute|unsure> 'contrast.note=<note>'`. Then check them with `ia.py finding list`.

External workers (a slash command, a plugin skill, a scanner) follow the same rule: run them, then turn every result
you keep into a finding in the schema of `references/schema.md`, with `source` set to the worker's name.

## No subagents on this host

Some hosts or sessions cannot launch subagents (no agent tool, or a mode that forbids it). The audit still runs; only
who does each pass changes. Tell the person once, at step 0, and say it again in "Finishing".

- **Run the passes yourself, sequentially, module by module, driven by the coverage map.** Take the first open cell
  from `python3 <skill-dir>/ia.py coverage status --run <run-dir>`, read that pass file, run it on that one module,
  record the cell with `ia.py coverage add`, and take the next. For `races-distributed`, walk the ten topics with the
  pass's starting searches on the module before recording it with `--topics`. Finish a module before opening the
  next, so a time-box leaves whole modules done rather than every module half done.
- When the time does not reach, say how many cells are left and let the person decide; only they can close with
  `--force-open "<reason>"`.
- **Writing passes** (proof, unit-tests, e2e-infra) run one at a time, still each in its own worktree, removed when done.
- **verify:** the judgment comes from a **different model** through a read-only CLI (the contrast rows of
  `references/workers.md`: Cursor's `agent` CLI in ask mode, or the read-only Codex CLI recipe there), given
  only the verify-high pass, the finding files, the branches and the run dir. A read-only CLI cannot run tests, so
  you, the orchestrator, rerun them in a throwaway worktree and record them as rerun by the orchestrator in
  `outputs/<id>-verify.txt`; the verifier judges that output. `references/passes/verify-high.md` has the details.
- **contrast** still uses a model of another family from the author's, as in its step, and preferably not the
  model that did verify, so each check comes from fresh eyes.

## The checklist

`references/checklist.md` has each step's acceptance criterion; `references/rubric.md` the severity, confidence and
effort scales; `references/schema.md` the finding and manifest fields; `references/workers.md` who does each step on
each host. Mark a step `in_progress` when you start it:

```bash
python3 <skill-dir>/ia.py step --run <run-dir> correctness in_progress
```

### Step 0: `baseline`

- Read: `references/passes/baseline-inventory.md`, `references/workers.md`.
- Worker: own pass on both hosts, plus the CLI.
- Do:
  1. `python3 <skill-dir>/ia.py detect --run <run-dir>`: stack, test command and dependency mode per repo; tools on
     the PATH; the worker table for this host, printing missing workers with their install commands.
  2. **The one-time worker question.** Add the plugin and slash-command rows `detect` could not check (it records them
     as `available: null`; see whether they exist in this session). Show the person every missing worker with its
     exact install command from `references/workers.md`, and ask once which to install. Install nothing without that
     answer. Declined rows use their fallback pass for the whole run; do not ask again in later steps. The `npx`
     measurement rows (dependency-cruiser, knip, jscpd) download the package on first use unless it is already a
     dependency of an audited repo: `detect` lists those under "ask before using", and they always go into this
     question.
  3. **Show the person the baseline plan** `detect` printed (test command, `deps`, and the suggested install it never
     runs on its own). `detect` proposes `deps: none` unless the dependency folder already exists and matches the
     lockfile (`symlink`); installing into the throwaway worktree only happens with `deps=install`, and you set that
     only after the person says yes. Fix the plan where detection was wrong or the stack is unknown:
     `ia.py baseline --run <run-dir> --set ALIAS KEY=VALUE` (it runs nothing; for
     example `test_cmd='["make","test"]'`, `env='{"DATABASE_URL":"..."}'`, `deps=install` once agreed).
     Baseline commands run with `CI=1` and `npm_config_yes=false`, so `npx` never downloads a package on its own.
  4. `python3 <skill-dir>/ia.py baseline --run <run-dir>` (optionally `--alias` and `--timeout`): runs each suite at
     the pinned SHA in a throwaway worktree and saves the raw output. Its default `--timeout` (1800 s per repo) is
     longer than a host's foreground command limit (10 minutes in Claude Code): run it in the background (Claude
     Code's `run_in_background`, a separate Cursor terminal) or pass a `--timeout` below that limit. If the host
     stops it anyway, `ia` stops the suite, removes the worktree and exits 143 (SIGTERM) or 129 (SIGHUP); run it
     again.
  5. `detect` also records `manifest.modules`: the modules of each repo (the folders under `src/modules`,
     `src/features`, `src/app`, `app`, `src/components`, and every other folder of `src/`). Steps 1 and 2 are
     closed against them (see "Coverage map" below). If the inventory shows that `detect` cut the modules wrong
     (missed some, or one module is really several), replace that alias's list before step 1:
     `ia.py set --run <run-dir> 'modules.<ALIAS>=["internal/orders","internal/billing","cmd/api"]'`. Each path is a
     directory at the pinned base, relative to the alias root (`<dir>/.` for the files directly in a directory); a
     later `detect` keeps the list (`manifest.modules_edited`).
  6. Run the baseline-inventory pass: modules, entry points, external dependencies, data stores. From it, choose the
     categories and record their order, and note real strengths, with `ia.py set` (never edit `manifest.json` by
     hand): `ia.py set --run <run-dir> 'sections.correctness=["auth","orders"]' 'sections.quality=["api"]'
     'strengths=["Every route validates its input (BACK/src/routes/orders.ts:12-30)"]'`.
- Closes: `ia.py baseline` marks `baseline` done when every repo has a result with parsed counts (a failing
  `coverage_cmd` only loses the coverage figure). For an unmeasured stack (no `test_cmd` in the detect plan), or when
  `baseline` says it could not parse the summary, run the suite yourself or read the raw output and record the numbers
  with `ia.py set --run <run-dir> baseline.<ALIAS>.result.passed=<n> baseline.<ALIAS>.result.failed=<n>
  baseline.<ALIAS>.result.total=<n>` (also `.coverage`, `.runner` and `.measured`); a repo with no test runner at all
  records `baseline.<ALIAS>.result.total=0`. A repo without `test_cmd` does not close the baseline until that manual
  result is set; the step closes by itself once every repo has a parsed or manual result.

### Step 1: `correctness`

- Read: `references/rubric.md`, `references/schema.md`, `references/verification-rules.md`.
- Workers (per `references/workers.md`):
  - General bugs: Claude Code `/code-review` per module; Cursor `/review-bugbot`; fallback
    `references/passes/correctness-general.md`.
  - Whole-repo security: Claude Code `claude-security`; Cursor and fallback `references/passes/security.md`.
  - Races and distributed systems: always `references/passes/races-distributed.md` (no external worker covers it).
  - Static analysis, supply chain and container: semgrep, gitleaks, trivy, osv-scanner when installed, interpreted
    with `references/passes/supply-chain-container.md`.
- Every candidate goes in with `ia.py finding add --run <run-dir> <file.json>` (or `-` for stdin), `verdict` set to
  `candidate`, with cites at the base. Merge duplicates found by different workers into one finding.
- **Coverage map.** Every module is visited by `correctness-general`, `races-distributed` and `security`, and the
  visit is recorded, even when nothing was found. Modules of the `ROOT` alias need only `security` (and
  `quality-lenses` in step 2). The pseudo-module `src/.` (or `.`) stands for the files sitting directly in that folder
  (bootstrap files, a root `Dockerfile`): visit it like any other module. Split the passes by module and, as each subagent returns, record
  its cells:

```bash
python3 <skill-dir>/ia.py coverage add --run <run-dir> --pass security --module BACK/src/modules/orders \
  --result nothing --note "checked authz on every route"
python3 <skill-dir>/ia.py coverage add --run <run-dir> --pass races-distributed --module BACK/src/modules/orders \
  --result found --topics 1,2,3,4,5,6,7,8,9,10
python3 <skill-dir>/ia.py coverage status --run <run-dir>
```

  `--result` is `found`, `nothing` or `n/a`; `--module` can repeat. A `races-distributed` cell is complete only with
  `--topics` listing every topic of the pass (1 to 10), also when the result is `nothing`: a topic you did not check is
  not covered. `n/a` says the pass does not apply to the module (a races pass on presentational UI code with no I/O
  and no shared state, a security pass on generated code): it needs `--note` with the reason, takes no `--topics`,
  and the report lists it apart from `nothing`, which means "looked and found nothing". Never use it to skip work
  that applies. Last write wins. `coverage status` prints the grid and the open cells (add `--pass` to see one pass).
- Closes: `ia.py step --run <run-dir> correctness done`, which refuses and lists the open cells. If the person
  decides a module stays out, `ia.py step --run <run-dir> correctness done --force-open "<reason>"` closes anyway,
  records the reason and the open cells in `manifest.coverage_waivers`, and the report shows it in "How it was done".

### Step 1: `proof`

- Read: `references/passes/red-test-proof.md` and the "Red for the right reason" section of `references/checklist.md`.
- Worker: own pass on both hosts, one subagent per candidate (or small group), each in its own worktree.
- Each candidate gets a local branch without upstream and one commit with only tests that fails on an assertion at the
  base. If red is not reproducible that way, or the fix needs a refactor, the candidate is discarded with a reason.
  The written proposal for the fix goes in `fix_summary`; no production code is changed.
- Findings that no code test can express (configuration, CI, container, supply chain, and `security` findings that
  live only in history or that a scanner verified) skip this step: they are confirmed under
  `references/verification-rules.md`, with `execution` (the command in `measurement.tool` and its saved output in
  `outputs.suite`) or `docs`, and no branch. `unverified` ones stay `candidate`.
- Record the result in one call, because a confirmed code finding with `execution` confidence is refused
  without `tests` and `red_reason` (add `fix_summary` with the proposal, and `prod_files` when you know them):

```bash
python3 <skill-dir>/ia.py finding set --run <run-dir> C-07 verdict=confirmed confidence=execution \
  branch=fix/c-07-short-name sha_test=<sha> \
  'tests=[{"path":"api/tests/test_orders.py","red":"2 of 2 fail","green":"","note":""}]' \
  'red_reason=<the assertion that fails at the base and why>' outputs.red=outputs/C-07-red.txt
```

  Save the raw red output under the run dir's `outputs/`. A discard is
  `ia.py finding set --run <run-dir> C-07 verdict=discarded 'reason=<why>'`.
- Then `python3 <skill-dir>/ia.py merge-check --run <run-dir>`: every pair of branches must merge cleanly; report
  conflicts to the person.
- Closes: `ia.py step --run <run-dir> proof done`. It warns, without refusing, if correctness candidates are left that
  were neither confirmed nor discarded: prove or discard them, or tell the person why they stay.

### Step 1.5: `tests`

- Read: `references/passes/unit-tests.md`, `references/passes/e2e-infra.md`.
- Workers: unit tests with Claude Code `superpowers:test-driven-development` or Cursor `obra/superpowers`, fallback the
  unit-tests pass; e2e with Playwright for the browser and the e2e-infra pass for emulators, compose and a throwaway
  database.
- One separate branch per repo for tests that prove no bug; record its name with
  `ia.py set --run <run-dir> baseline.<ALIAS>.tests_branch=<branch>`. New tests must be green at the base; a new test that fails becomes a step-1
  candidate and goes through `proof`.
- Run `ia.py merge-check --run <run-dir>` again: the tests branch must combine with the finding branches.
- Closes: `ia.py step --run <run-dir> tests done`.

### Step 2: `quality`

- Read: `references/passes/quality-lenses.md`, `references/rubric.md`.
- Workers: the four lenses of the pass, supported by Claude Code `feature-dev:code-architect` or Cursor
  `wshobson/agents`; measurements with dependency-cruiser, knip and jscpd for TypeScript/JavaScript (or the
  language's equivalents named in the plan's `measure`). Without a tool, label the number "not measured with tools".
- Each finding: `report` `quality`, a `suggestion`, an `effort`, and `measurement` when it is quantitative. The
  resilience and lying-documentation dimensions belong here.
- Record each module the lenses visited with `ia.py coverage add --run <run-dir> --pass quality-lenses --module
  ALIAS/path --result found|nothing|n/a` (`n/a` with `--note`).
- Closes: `ia.py step --run <run-dir> quality done`, which refuses while a module has no `quality-lenses` cell;
  `--force-open "<reason>"` works as in step 1.

### `contrast`

- Read: `references/passes/contrast.md`, the contrast row of `references/workers.md`.
- Worker: Claude Code `/codex:adversarial-review` (Codex plugin); Cursor's `agent` CLI with another model in ask mode;
  fallback the contrast pass in a fresh subagent. Read-only.
- **Pick a model of a different family** from the one that wrote the findings. If none is available, the contrast
  still runs, with another model of the same family, and every finding it reviews gets
  `ia.py finding set --run <run-dir> C-07 contrast.model=<model> contrast.same_family=true contrast.verdict=<v>`.
- Every finding gets `contrast.verdict` `agree`, `refute` or `unsure`, and every refute a `contrast.scope`:
  `severity` (the finding is real, the severity is off) or `finding` (the claim does not hold).
- Review each refute before the filter. `scope=severity`: lower the severity yourself with
  `ia.py finding set --run <run-dir> C-07 severity=<level>`; the finding stays in the report. `scope=finding`: check the
  cited code. If the refute is right, discard it (`verdict=discarded 'reason=<why>'`). If it is wrong, rebut it with
  evidence: `ia.py finding set --run <run-dir> C-07 contrast.rebutted=true 'contrast.rebuttal=<why the finding holds,
  with a cite>'`. Never overwrite `contrast.note`: it is the contrast's objection. A rebutted finding stays visible and
  the report prints both the objection and your rebuttal. An unreviewed `scope=finding` refute hides the finding.
- Tell the report who wrote the findings: `ia.py set --run <run-dir> author_model=<model>`; "How it was done" states it
  and each contrast model. The reports never print pass names, only external workers by name.
- Closes: `ia.py step --run <run-dir> contrast done`.

### `verify`

- Read: `references/passes/verify-high.md`.
- Worker: own pass in a **fresh** subagent that never saw the finder's reasoning: it gets only the finding file, the
  branch and the run dir. Every `high` is re-verified; if it does not hold, lower the severity or discard it. Without
  subagents, a different model through a read-only CLI judges and you rerun the tests ("No subagents on this host").
- Closes: `ia.py step --run <run-dir> verify done`.

### `filter`

- Read: the "Filter" section of `references/checklist.md`.
- Mark exclusions first (`ia.py finding set --run <run-dir> C-12 exclude=refactor`), then run
  `python3 <skill-dir>/ia.py filter --run <run-dir>` (`-n` sets how many quality findings go in "Start here", default
  5). It sets `shown` on every finding and prints the shown and total counts; tell the person both.
- Closes: `ia.py filter` marks `filter` done.

### `prose`

- Read: `references/passes/owner-prose.md`.
- Worker: own pass. Writes `audience.title`, `audience.what_happens` and `audience.fix_summary` for every shown finding,
  in the run's `lang`, for the owner team: no audit jargon, no blame, inferences labelled, impact but no exploitation
  recipe. Run the pass's forbidden-terms check.
- Closes: `ia.py step --run <run-dir> prose done`.

### `hygiene`

- Read: the "Hygiene" section of `references/checklist.md`.
- Run `python3 <skill-dir>/ia.py hygiene --run <run-dir>`: secrets and 40-character ids in branches and saved
  outputs, unmasked secrets in rendered reports, local tool files in commits, a committable run dir. Fix every problem (amend the branch, mask the output)
  and run it again until it is clean. Check action SHAs against their comments by looking them up
  (`references/verification-rules.md`, rule 7).
- Closes: `ia.py step --run <run-dir> hygiene done`.

### `render`

- Read: the "Optional publish" section of `references/checklist.md` when `publish` is on.
- Worker: the CLI only; the HTML comes only from the data and git, from `assets/template.html` with `assets/theme.css`.
- Do:
  1. `python3 <skill-dir>/ia.py cite-check --run <run-dir>` until it is clean: every cite must resolve at the base.
  2. `python3 <skill-dir>/ia.py render --run <run-dir>` (`--report correctness|quality|both`, `--theme FILE.css` to
     swap the stylesheet). It refuses to run before `filter` is done and writes both HTML files into the run dir.
  3. `python3 <skill-dir>/ia.py hygiene --run <run-dir>` once more: it also scans the rendered HTML for unmasked
     secrets (render masks every cited and diff line, so a hit means something slipped through; fix it and render
     again).
  4. If `publish` is on: `python3 <skill-dir>/ia.py publish --run <run-dir>` (it refuses before `filter`), then show
     the person `publish/commands.sh`: issues first, then draft PRs that reference them (`Refs #N.`, never
     `Closes`: the branch only adds the failing test), every `gh` with `--repo`, the push commented out and the base
     branch (`main`) to check. They review it and run it, or not.
- Closes: `ia.py render` marks `render` done.

## Finishing

Tell the person, briefly: where the run dir and the two reports are; shown and total counts per report; the branches
(one per confirmed finding plus the tests branch), all local and unpushed; which steps used a fallback pass instead
of an external worker; which model contrasted which and whether it was the same family; anything `unverified` that
stayed out of the reports; and, with `publish`, that the `gh` commands are ready for them to review and run.
