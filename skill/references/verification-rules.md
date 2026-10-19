# Verification rules

For findings that a red test cannot prove (configuration, container, CI, supply chain, documentation) and for every
claim the reports make. The idea underneath all of them: until you have run it, it is a guess, and a guess written as a
fact costs the reader's trust in every other finding. Label what you did not run as `unverified` and keep it out of
the reports.

## 1. Look at what the repo does not show before saying something is absent

Shared or private CI workflows, organisation templates, `AGENTS.md`, editor and tool configuration, and settings that
live outside the repository can already do what you are about to call missing (coverage upload, dependency scanning,
secret scanning). Fetch and read them first. If you cannot reach them, write "not visible from this repository", never
"there is none".

## 2. Check a dependency range at its lowest end too

A green build only proves the versions that happened to resolve. Resolve the declared range at its floor (the lowest
allowed version of each direct dependency), install it and run the suite there. The same goes for a symbol: "this
constant or function exists" is true only for some versions of the library, so check it at both ends of the range.

## 3. A check is proven only when you have seen it fail

For every gate (coverage threshold, drift check, lint rule, "this image has no shell"), make it fail on purpose and see
it fail, then make it pass. Break it in the state the check actually inspects: if it compares against the last commit,
the breakage has to be committed, not just edited.

## 4. Know whether a control checks the artifact or the file that describes it

Hash pinning proves that what was downloaded matches the hash beside it; it says nothing about whether that file is
the current one. Before writing that a flag or tool protects against something, name the exact failure it stops and
reproduce that failure.

## 5. Do not describe intentions as guarantees

"Generated from X, so they always match" is a convention unless something enforces it. Either point at the check that
enforces it, or call it a convention. A finding may suggest adding the check.

## 6. Treat "not found" as possibly "not allowed"

Many APIs answer an unauthenticated or unauthorised request with "does not exist" or an empty list. Confirm who you are
authenticated as before concluding that an issue, repo, project, package or image is missing.

## 7. Look external references up; never write them from memory

Commit SHAs of actions, release tags, image digests and package versions are checked against the source (its API, its
registry). A SHA can exist and still belong to a different tag than the comment beside it says; check both existence
and correspondence. Tools that pin their own versions are checked the same way.

## 8. Separate an intermittent failure from a permanent one

Before calling a failure flaky, confirm that whatever it downloads or calls actually exists. A missing release fails on
every retry. Then rerun the whole job, not only the failed part, before concluding anything.

## 9. Know which actions destroy work or reach people

Renaming a branch that has an open PR closes the PR. A hard reset discards uncommitted tracked changes. Staging
everything sweeps local tool folders (`.serena/`, `.idea/`, editor settings) into a commit. An issue, once created, has
already notified people, and deleting it does not undo that. The skill never does the last one on its own; for the
others, stop and check first.

## 10. Search for what the target's CI scanners will flag

Secret scanners match on shape, not meaning: any 40-character alphanumeric identifier (a long test name, a fixture id)
can be reported as a verified secret. Search the branches and saved outputs for the pattern instead of reasoning about
whether it looks fake. `ia.py hygiene` does this for the branches and outputs of a run.

## 11. After a fix, rerun the check that found the problem

A fix can undo another fix or not work at all (a `|| true` that swallows the failure it was meant to cause). After each
fix, repeat the original evidence (build, run, request, permission check, red test) where the problem lives, not only
the unit suite.
