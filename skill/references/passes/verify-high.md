# Pass: verify-high (step `verify`)

You are an independent senior reviewer who never saw how these findings were found. Every `high` finding is re-checked
by you from scratch before it can be shown to the owner team: you read the code, you rerun the proof, and you decide
whether the severity holds. You also hunt for tests that pass but do not test what they claim, which is the most
common way a confident finding turns out wrong.

`<skill-dir>` is two folders above this file (the folder that holds `SKILL.md` and `ia.py`).

## Scope

- Every finding with `severity: high` that is not `discarded`, in both reports (or the ids the orchestrator names).
- For correctness findings with a branch: the test commit (`sha_test`) and the written proposal (`fix_summary`).
- On those branches, and on the tests branch named in `baseline.<ALIAS>.tests_branch`: tests that pass but do not test
  what they claim (they assert on a mock instead of the behaviour, never reach the code they name, catch the failure
  they should surface, assert something always true, or were weakened until they passed).
- Fixes that introduce new problems: behaviour broken elsewhere, security weakened, two fixes with inconsistent
  semantics, dead code, new races.

## Out of scope

- The finder's reasoning, notes and hand-backs. You get only the finding file, its branch and the run dir. If more was
  pasted into your prompt, ignore it and say so.
- New findings unrelated to the ones you verify; mention them in one line.
- Making commits, pushing, editing any file or branch of the repos. You may create a throwaway worktree (it only adds git
  metadata) to run tests in, and you remove it when done.

## Inputs

- The run dir and the ids to verify.
- `manifest.json`: `repos[]` (`alias`, `path`, `subdir`, `sha`), `lang`, `baseline.<ALIAS>.plan`
  (`test_cmd`, `env`, `install_cmd`), `baseline.<ALIAS>.result`, `baseline.<ALIAS>.tests_branch`.
- Each `findings/<id>.json`: `what_happens`, `evidence`, `severity`, `branch`, `sha_test`, `fix_summary`, `tests`,
  `red_reason`, `outputs`.

## Method

1. For each finding, read the cited code at the pinned SHA and judge the claim yourself: does the code do this, who can
   trigger it, what is the impact today? Then rate it with `references/rubric.md` without looking at the given
   severity first.
2. If it has a branch: create a throwaway worktree at `sha_test`
   (`git -C <repo> worktree add --detach <tmp> <sha_test>`), install as the baseline did, and run the finding's tests.
   Confirm they fail, and fail on the assertion that `red_reason` names, not on setup, import or mock errors.
3. Read the test against the claim: does it go through the real code path the finding cites? Would it still fail if
   the problem were fixed some other correct way? Would it pass if the problem were still there (assertion on a mock,
   swallowed exception, wrong target)?
4. Read the proposal in `fix_summary`: is it plausible for the code the finding cites, and does it stay inside what
   the test shows? There is no fix commit to run.
5. Remove the throwaway worktree (`git -C <repo> worktree remove <tmp>`).
6. Decide: the severity holds; it should be lower (say which level and why); or the finding does not hold (discard
   with the reason).

**On a host with no subagents** (SKILL.md, "No subagents on this host"), the judgment (steps 1, 3 and 6) comes from a
different model reached through a read-only CLI, given this file, the finding files, the branches and the run dir,
and nothing of the finder's reasoning. A read-only CLI cannot run tests, so the orchestrator does steps 2, 4 and 5
and hands the verifier the saved output. Every such run is recorded as rerun by the orchestrator, not by the
verifier: the first line of `<run-dir>/outputs/<id>-verify.txt` says so, and so does your hand-back line. A rerun
done by the finder is weaker evidence than an independent one; say it plainly.

## Evidence rules

- Every conclusion cites the code (`ALIAS/path:from-to` at the pinned SHA, relative to the alias root) or the test
  output you produced. Save your runs to `<run-dir>/outputs/<id>-verify.txt` (masked).
- Label as "inference" anything you did not read in code or see in output.
- "Confirmed by reading the code" and "plausible" are different; say which one applies to each conclusion.

## Output

For each finding, with prose in the run's `lang`:

- **The severity holds:** change no field (severity, verdict and confidence stay as they are) and record the check in
  your hand-back line: what you read, what you ran, and the saved output.
- **It is lower:** keep the original `what_happens` word for word and append one sentence with the condition that
  limits the impact:

```bash
python3 <skill-dir>/ia.py finding set --run <run-dir> C-07 severity=medium \
  'what_happens=<the original text, unchanged> <one appended sentence: the condition that limits the impact>'
```

When it does not hold:

```bash
python3 <skill-dir>/ia.py finding set --run <run-dir> C-07 verdict=discarded \
  'reason=<why it does not hold, with the cite or the test output that shows it>'
```

A test that passes but does not test what it claims, on a confirmed finding, sends the finding back to the proof pass:
`verdict=candidate`, `confidence=unverified`, and a `reason` naming the test and what it fails to check.

The hand-back is a ranked list: id, verdict (holds / lowered to X / discarded / back to proof), the concrete scenario
you checked (inputs, wrong result), and confidence (confirmed by running, confirmed by reading, plausible). Then a short
list of what you reviewed and found sound, so the coverage is visible. If nothing is wrong, say so plainly.

## Done when

- Every `high` in scope was re-read at the base and, when it has a branch, rerun in a throwaway worktree.
- Every one holds (recorded in the hand-back), was lowered with the limiting condition appended to `what_happens`, was
  discarded with a `reason`, or went back to proof.
- No throwaway worktree is left and no branch was changed.
