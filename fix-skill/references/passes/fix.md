# Pass: fix

You write the fix for one finding (or, in a group PR, for one member at a time) as a new commit on top of the red
test that inherited-audit published. Another agent reviews your diff afterwards; you do not judge it yourself.

## Input

- The run directory, the finding id and the worktree: `<run>/fix/wt-<branch>`. Work only there, never in the person's
  checkout.
- `<run>/fix/<branch>/<id>.md`, written by `fix start`: what happens, the proposed fix, the production files in scope,
  the red test and why it fails, and the test command.
- `findings/<id>.json` of the run for anything else (`tests[]`, `prod_files`, `fix.extra_files`).

## Steps

1. **Read the context and the red test first.** The test is the spec. Read `red_reason` and the assertion that fails.
2. **Find the cause** described in "What happens", in the production code at the worktree's HEAD.
3. **Make the smallest production change** that makes the red test pass for that reason:
   - Start from the proposed fix. You may deviate from it, saying why in the commit body.
   - Touch only the production files in scope. When another production file is truly needed, add it with the reason:
     `python3 <ia> finding set --run <run> <id> 'fix.extra_files=["path"]'`.
   - You may add **new** test files that cover an edge of your fix. Existing test files stay as they are.
4. **Run the finding's tests** (the targeted command from the context, filtered to the red test's class or file) and
   save the raw output to `<run>/outputs/<id>-green.txt`. Mask secrets: `python3 <ia> mask`.
   - If `outputs/<id>-typecheck.txt` exists, rerun the command recorded in its first lines on your fix and save the
     output to `<run>/outputs/<id>-fix-typecheck.txt`.
5. **Commit.** Stage explicit paths, never `git add -A`. Write one commit with this shape:

   ```
   fix(<scope of commit 1>): <what changes, imperative, <= 100 chars with the prefix>

   <why this is the cause, and anything you did differently from the proposed fix>
   Ran: <the targeted command> -> <n of n pass>
   ```

   Quote every command relative to the repo root, as a reader of the PR would run it (`./gradlew test --tests
   '...ApiTokenValidationServiceTest'`), never through the run's helper scripts or any absolute path of this machine
   (`/Users/...`, `/private/...`, `/tmp/...`, the run dir). The message is public once pushed; `fix check` fails on one.

   No issue reference and no closing keyword: the PR body closes the issue. No attribution of any kind.
6. Hand back the commit sha, the files changed, the green line, and whether you deviated from the proposal.

## Stop without a commit (`blocked`)

Stop, change nothing, and hand back the reason in one sentence when the fix needs:
- a design decision the owner team has to make;
- a data migration;
- a change to an API contract, a message or an event that other systems read;
- a change in another repo;
- anything outside the scope above that you cannot justify as part of the cause.

A blocked finding is a valid result. The orchestrator records it.

## Revision round

If the review returns a claim that is not CONFIDENT, you get its evidence. Amend your commit (`git commit --amend`,
same rules) to address it, rerun step 4, and hand back again. There is exactly one revision round.
