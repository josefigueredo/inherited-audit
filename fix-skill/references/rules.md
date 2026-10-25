# Rules of a fix

## Green for the right reason

The red test passes because the cause in `what_happens` is gone. A green test does not prove that by itself:
- A fix that hard-codes the test's value, branches on the test's input, or swallows the exception is also green.
- That is why the reviewer is never the fixer, and why `targeted` is a separate claim from "the suite passes".

## Where it is proven

On the merge result the PR would have: the PR base read from the PR (`origin/develop`, `origin/main` ...), merged into
the branch in a throwaway worktree, never committed to the branch.
- The pinned audit base is old by the time anyone fixes anything.
- A base that moved can already contain the fix (`moot`), or can conflict with the branch (reported, decided by the
  person).

## "No new failures"

`fix start` saves the names of the tests that pass on the merge result before the fix. `fix check` requires every one
of them, plus each test of the finding, to pass after it.
- Without junit reports, the comparison falls back to counts and the output says "by counts": failing now may be at
  most failing at start minus the red tests, and the total may not shrink.
- A rough count in prose is never a substitute.

## Scope

`fix check` looks at the diff from the red test, or from the previous member's fix in a group. It accepts:
- `prod_files`;
- the paths in `fix.extra_files`, each with its reason;
- new test files.

It rejects:
- an edit to an existing test, including any byte of a red test anywhere on the branch;
- a tooling file;
- any other path.

## Red flags: stop and go back to the procedure

- "The test is wrong, I'll adjust it". The test is the spec. If it truly is wrong, the finding is `blocked`, with that
  reason.
- "I'll just push it to save them a step". Commands only.
- "Same agent, but I reviewed carefully". The reviewer is another agent.
- "About 900 tests passed" without `fix check`. That is a guess, not a measurement.
- "I'll fix both group members on their own branches and merge them later". One worktree, in order.
- "I'll write `Closes #N` in the commit so it links". The PR body does that.
- "I'll write a clean PR description". The audit's body stays; `fix publish` rewrites only the draft note and the
  `Refs` lines.
