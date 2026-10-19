# Pass: unit-tests (step 1.5, fallback)

You add the unit tests the system is missing, so the team inherits a safety net and the audit can say what the code
really does. This is the red rule in reverse: every new test is **green at the pinned base** and asserts real
behaviour. A new test that fails is not a test to fix; it is a bug to report.

`<skill-dir>` is two folders above this file (the folder that holds `SKILL.md` and `ia.py`).

## Scope

- The modules your prompt names, chosen from the baseline: large modules with low or no coverage, business rules,
  parsers, mappers, permission checks, state machines.
- Tests in the project's own runner, style and folder layout, using its existing fixtures and helpers.
- One branch per repo for these tests, in the worktree you own.

## Out of scope

- Changing production code, even to make it testable. If a module cannot be tested without a refactor, say so in the
  hand-back; that becomes a quality finding, not a change.
- Tests for findings already in the run: those belong to the finding's branch (`red-test-proof.md`).
- End-to-end tests and local infrastructure: `e2e-infra.md`.
- Pushing or setting an upstream. Never.

## Inputs

- The run dir, the scope, and the worktree path you own (one worktree per agent; if none was given, create one at the
  pinned SHA: `git -C <repo> worktree add --detach <path> <sha>`).
- `manifest.json`: `repos[]` (`alias`, `path`, `subdir`, `sha`), `baseline.<ALIAS>.plan` (`test_cmd`, `coverage_cmd`,
  `env`, `deps`, `install_cmd`), `baseline.<ALIAS>.result` (`coverage`, failures already present),
  `baseline.<ALIAS>.tests_branch` (reuse it if another agent already created it; coordinate through the orchestrator).

## Method

1. Create or switch to the tests branch: `git -C <worktree> switch -c test/<system>-coverage <sha>` (no upstream).
   When a component has no test runner, the branch's first commit adds the minimal runner config (a development
   dependency, a config file, a `test` script; prefer the runner the repo's other components use) and nothing else,
   and the hand-back says so. Never break the build: run the component's build or type-check after each commit and
   fix the tests, not the production code, when they break it.
2. For each module, read it at the base and list its behaviours: inputs and outputs, edge cases, error paths. Prefer
   behaviour a caller depends on over internal details.
3. Write one test per behaviour, named after the behaviour. Assert outcomes (returned values, persisted state, emitted
   calls at a real boundary), not that a mock was called with whatever the code happens to pass. Keep the libraries
   the code calls real and fake only what lies beyond them (an in-memory server, a closed port), as
   `red-test-proof.md` asks.
4. Run the new tests. Every one must pass at the base. If one fails:
   - first check it is not your own setup (wrong fixture, missing variable); fix the test if so;
   - if the code really behaves wrongly, remove the test from this branch and file a correctness candidate (Output);
     the proof pass builds its red branch.
5. Run the full suite with the baseline's command: no new failures against the baseline result. Run coverage if the
   plan has a `coverage_cmd` and note the before and after numbers.
6. Commit in small groups with conventional commits (`test(<scope>): cover <behaviour>`), staging explicit paths only
   (never `git add -A`), no AI attribution, neutral messages.
7. Avoid test names or fixture ids that form 40-character alphanumeric runs; secret scanners report them.

## Evidence rules

- "Green at the base" is shown by a saved run: `<run-dir>/outputs/tests-<ALIAS>-unit.txt` (masked).
- Coverage numbers come from the coverage tool's output; otherwise say "not measured with tools".
- A candidate filed from a failing test cites the production lines at the pinned SHA (`ALIAS/path`, relative to the
  alias root) and quotes the assertion message in `what_happens`.

## Output

1. The branch with its commits, and the branch name recorded with
   `python3 <skill-dir>/ia.py set --run <run-dir> baseline.<ALIAS>.tests_branch=<branch>`.
2. The saved suite output under `outputs/`.
3. For each test that exposed a bug, one candidate, prose fields in the run's `lang`:

```bash
python3 <skill-dir>/ia.py finding add --run <run-dir> - <<'EOF'
{"report": "correctness", "category": "<a category from sections.correctness>", "dimension": "bug",
 "title": "<one technical line>", "verdict": "candidate", "severity": "medium", "confidence": "unverified",
 "source": "unit-tests",
 "what_happens": "<what the test expected, what the code returned, who is affected>",
 "evidence": [{"cite": "BACK/src/pricing/discount.ts", "from": 30, "to": 37, "note": "rounds before applying the cap"}]}
EOF
```

4. A hand-back: modules covered, tests added (count), coverage before and after, candidates filed, modules that need a
   refactor to be testable.

## Done when

- Every new test passes at the pinned base and the full suite shows no new failures against the baseline.
- `baseline.<ALIAS>.tests_branch` names the branch, which has no upstream.
- Every failing test became a candidate in the run instead of staying on the branch.
