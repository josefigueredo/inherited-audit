# Pass: red-test-proof (step 1, `proof`)

You turn correctness candidates into proof: one local branch per candidate, with one commit that holds only tests and
fails at the pinned base for the right reason. The team that receives this will look for any weak point, so the
evidence has to be honest and impossible to argue with. A discard with a good reason is a valid and valuable result;
a forced red is not.

`<skill-dir>` is two folders above this file (the folder that holds `SKILL.md` and `ia.py`).

## Scope

- The candidate ids your prompt names (one, or a small group of related ones), all `verdict: candidate`.
- Writing tests, running them, making commits on your own local branch, recording the result in the run.
- Writing the proposal for the fix in `fix_summary`. You never write the fix itself.

## Out of scope

- Candidates not given to you, and any branch that is not yours. Do not touch the main worktree of the repo.
- Pushing, setting an upstream, opening PRs. Never.
- Refactors, new functionality, formatting changes, dependency upgrades, documentation in the branch.
- Findings with `dimension` `supply-chain` or `container`, and `security` findings whose cites all carry `@commit` or
  that carry `measurement.tool`: skip them. They are confirmed with a command and its saved output, and they never get
  a branch. Any other finding that no code test can
  express (configuration, CI) is left unchanged and listed in your hand-back, so the orchestrator verifies it with
  `references/verification-rules.md`.

## Inputs

- The run dir, the candidate ids, and the worktree path you own (one worktree per agent; if none was given, create
  one: `git -C <repo> worktree add --detach <path> <sha>`).
- `manifest.json`: `repos[]` (`alias`, `path`, `subdir`, `sha`), `baseline.<ALIAS>.plan` (`test_cmd`,
  `env`, `pre`, `deps`, `install_cmd`) and `baseline.<ALIAS>.result` (the numbers you compare the suite against).
- Each finding: `python3 <skill-dir>/ia.py finding list --run <run-dir>` and `findings/<id>.json` (cites, scenario,
  the test design the finder left in its hand-back if the orchestrator passes it, `base` for stacked branches).

## Method

For each candidate, in the order given:

1. **Branch.** `git -C <worktree> switch -c fix/<id-lowercase>-<short-name> <base>` with no upstream, where `<base>` is
   the pinned SHA, or the finding's `base` when it depends on another finding's branch. If that base branch does not
   exist yet, skip the candidate, continue with the others and retry at the end; if it still does not exist, record
   `verdict=blocked` with `reason` naming the missing branch. When the base is two branches ("A + B"), create the
   branch from A and then `git merge --no-ff B`, and say so in the hand-back.
2. **Dependencies** the way the baseline did: link the dependency folder from the repo when `deps` is `symlink`; run
   `install_cmd` only when `deps` is `install` (the person agreed to it in step 0). With `deps: none`, ask the
   orchestrator instead of installing. Keep installed folders out of git (`.git/info/exclude`).
3. **Commit 1, tests only.** Write the smallest test that exercises the problem through code that exists at the base
   (the service, the route, the component), in the project's own test style and runner. Stage explicit paths (never
   `git add -A` or `git add .`, which sweeps in local tool folders such as `.serena/` or `.idea/`). Conventional commit,
   neutral message, no blame, no AI attribution: `test(<scope>): <what the test shows>`.
   - **Never mock the suspect library.** When the finding goes through a library (queue, HTTP client, ORM, database
     driver, cache client, parser), the test uses the real library at the version in the lockfile, fed with the input
     the code really builds (the job id, payload, key or query the code assembles), and fakes only what lies beyond
     it: an in-memory server, a closed port, a stub endpoint. A double that replaces the library's call never runs the
     library's own checks, so the red would prove a different, weaker problem and hide the real cause.
   - **No test runner in the component.** When the code you must test has no test runner, add the
     minimal runner config in commit 1 together with the test (a development dependency, a config file, a `test`
     script), and say so in `tests[].note` and in the hand-back: it is test infrastructure, not production code.
     Prefer the runner the repo's other components already use. Never break the build: the component's build and
     type-check must still pass with commit 1.
   - **Type-check commit 1.** Run the stack's type-check or compile command (for example `npx tsc --noEmit`, `mypy`,
     `go vet`, `cargo check`) on commit 1 too, and save it to `outputs/<id>-typecheck.txt`. A test-only branch must
     pass it like any other change. If it cannot (the runner needs an import form the type-checker rejects, say),
     say why in `tests[].note`; that is the first thing a reviewer will try.
4. **Run it** and save the raw output to `<run-dir>/outputs/<id>-red.txt` (mask secrets).
5. **Red for the right reason.** The test must fail on **an assertion about the code at the base SHA that reproduces
   the problem**, and the failure message must show it. These are **not** a valid red:
   - a module that does not exist, or any broken `import`;
   - an error in the test's own setup (fixture, database, environment, missing variable);
   - a badly built `mock` or fake whose contract differs from the real one;
   - a type error or compile error in the test.
   If the test only fails because it imports something new (an extracted helper that does not exist at the base),
   rewrite it to go through the existing code.
6. **Never bend a test to force red.** If making it fail means asserting something other than the problem, or
   asserting an implementation detail the problem does not involve, discard the candidate.
7. **Races and distributed flaws** use the deterministic design from the races pass: barriers or latches that hold both
   actors after the check, two connections with explicit transactions, fake clocks, two service instances standing for
   two replicas, a dependency stub that never answers plus a test deadline. No sleeps-and-hope, no loops of a thousand
   runs. If it cannot be made deterministic, discard with that reason; the finding stays `unverified`. The
   never-mock rule of step 3 applies here too: the stub stands for the server behind the library, never for the
   library.
8. **Discard** (`verdict=discarded`, with `reason`) when: the red cannot be reproduced with an assertion; the fix needs
   a refactor. Leave the branch with whatever it has, or delete it if it ended up empty.
9. **Stop at the red test, with a written proposal.** There is no second commit and no production code change. Write
   the proposal for the fix (one or two sentences, neutral prose in the run's `lang`) for `fix_summary`.
10. **Record** the result in one `ia.py finding set` call (see Output).

## Evidence rules

- Every number in `tests[].red` comes from the saved raw output ("2 of 2 fail", "14 of 14 pass").
- `red_reason` quotes or paraphrases the failing assertion message from `outputs/<id>-red.txt` and says why that
  assertion is the problem, not a setup error. Write it, and every `tests[].note`, from the start as neutral prose
  for the owner team in the run's `lang`: the report shows them as they are. No audit jargon (no "candidate", no
  "red for the right reason", no pass names), no blame; code facts, paths and numbers stay exact.
- `tests[].path` and `prod_files[]` are relative to the **repo top level** (what git uses); cites stay
  `ALIAS/path` relative to the alias root.
- If a test also fails at the base for something that is not the problem (a fake client with another contract, a
  flaky dependency), say so in `tests[].note`: it is the first thing a reviewer will find.
- Before handing back, search your commits and outputs for 40-character alphanumeric runs (long test names, fixture
  ids) that secret scanners report; rename them.

## Output

Per candidate, the branch with its commits and the raw outputs under `<run-dir>/outputs/`. Then one call:

```bash
python3 <skill-dir>/ia.py finding set --run <run-dir> C-07 verdict=confirmed confidence=execution \
  branch=fix/c-07-short-name sha_test=<sha of commit 1> \
  'tests=[{"path":"api/tests/checkout/test_stock_race.py","red":"2 of 2 fail","green":"","note":""}]' \
  'red_reason=<the assertion that fails at the base and why it shows the problem>' \
  'fix_summary=<the written proposal, one or two sentences>' \
  'prod_files=["api/src/checkout/service.ts"]' outputs.red=outputs/C-07-red.txt
```

`prod_files` (optional) are the production files the proposal would touch. A discard or a block is:

```bash
python3 <skill-dir>/ia.py finding set --run <run-dir> C-07 verdict=discarded 'reason=<why, in the run lang>'
python3 <skill-dir>/ia.py finding set --run <run-dir> C-08 verdict=blocked 'reason=base branch fix/c-03-x does not exist'
```

The hand-back is a compact table: id, branch, base, verdict, tests with their red count, and one line per discard
or adaptation that matters.

## Done when

- Every candidate given to you is `confirmed` with a branch, `sha_test`, `tests`, `red_reason` and a saved red output,
  or `discarded`/`blocked` with a reason.
- No branch has an upstream; nothing was pushed; every commit holds only tests.
- Every confirmed finding has a `fix_summary` proposal.
