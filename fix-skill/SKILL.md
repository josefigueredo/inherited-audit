---
name: inherited-fix
description: Use when an inherited-audit run has published red-test branches or draft PRs and someone asks to fix one or more of those findings, to "create the solution" for a failing-test branch, or to leave a draft audit PR ready to become a fix PR. Not for findings without a red-test branch, and not for writing the audit itself (use inherited-audit).
compatibility: python3 3.9+ (standard library only), git 2.38+, gh (read-only lookups). Needs the inherited-audit skill installed next to this one.
---

# inherited-fix

You take findings that an inherited-audit run proved with a red test (one commit on a published branch, a draft PR
that references the issue) and add the fix as reviewed commits on that same branch. You prove it on the merge result
the PR would have, have another agent review it, and prepare the exact commands that turn the draft PR into a fix
PR. **The person pushes and edits the PR; you never do.**

## The CLI

Everything mechanical goes through the inherited-audit CLI: `python3 <ia> fix <action> --run <run-dir> ...`. `<ia>` is
`ia.py` in the `inherited-audit` skill folder, the sibling of this skill's install folder: with this skill installed at
`~/.claude/skills/inherited-fix`, it is `~/.claude/skills/inherited-audit/ia.py`. Use the installed path; do not resolve
symlinks. In a checkout of the repo, the path is `../skill/ia.py`, next to `fix-skill/`. Exit codes: 0 ok, 1 the command found problems,
2 usage error, 3 an external tool failed or is missing, 4 ia itself failed.

| Action | What it does |
|---|---|
| `fix plan [--ids C-24,C-01] [--severity high] [--repo API]` | Lists the PR branches to fix, each with PR number, base and members. Read-only (git, `gh pr list`). |
| `fix start <C-24 or branch>` | Creates a worktree on the PR branch and a context file per finding. Runs the suite on a throwaway merge of the PR base and records the passing tests by name. Marks members already fixed upstream `moot`. |
| `fix check <id>` | Checks the commits, scope, frozen tests, messages and hygiene, then runs the full suite on the merge result, compared with the start. Writes `fix.check`. |
| `fix done <id>` | Records a checked and reviewed fix, or a `blocked`/`declined` one, and removes the worktree once nothing is left. |
| `fix publish [--partial]` | Writes `<run>/fix/commands.sh`. Never runs it. |

## Before the first fix of a run

The audit stopped at the red test on purpose: changing another team's production code is their call. Ask the person
once per run whether the owner team agreed to receive fixes, or whether the person takes that decision. Record the
answer with `python3 <ia> set --run <run-dir> fix.authorized_by='<who and how>'`; `fix start` refuses without it.

## Procedure

1. **Plan.** Run `fix plan` and show it. The unit of work is the **PR branch**, not the finding:
   - A single-finding PR is its own `fix/c-NN-*` branch.
   - A group PR is its `audit/pr-N` branch. Its members share production files by construction, so you fix them **in
     order, in one worktree**: one fix commit per finding, with `fix check` after each.
   - Never fix group members on separate branches to merge them later.
   - Different PR branches can go in parallel, one worktree each.

   If the person names one finding that belongs to a group, say so and fix the group's branch.
2. **Start.** Run `fix start <id or branch>` (add `--timeout` for slow suites). It proves on a throwaway merge of
   `origin/<PR base>` into the branch, with the base read from the PR (often `develop`, never assumed `main`). Act on
   what it prints:
   - `moot`: the test already passes on the PR base, so it was fixed upstream. Report it and do not fix it.
   - `conflict`: the branch no longer merges with the moved base. Stop and let the person decide: rebase the red
     branch first, or fix on the old base and leave the conflict to the PR.
   - `by counts`: the plan has no junit reports, so "no new failures" is only a count. Say so in your report.
   - `--base-ref <ref>` is only a test aid for a sandbox clone without a remote: it merges that local ref. Everything
     shown to the person still names the PR's real base from gh.
3. **Fix**, one subagent per PR branch, working only in `<run>/fix/wt-<branch>`. Give it
   `references/passes/fix.md`, the context file `fix start` wrote, and the finding id. For a group, go member by
   member: fix, then `fix check`, then review, then `fix done`, then the next member.
4. **Check.** Run `fix check <id>`. Exit 1 lists every problem: send them back to the fixer. Never edit the record to
   get past a check.
5. **Review**, with a different agent from the fixer, and a model that has not judged this finding before (not the
   finding's `contrast.model`). Prefer another model family when the host has one, through the Codex or cursor-agent
   read-only recipes in the inherited-audit `references/workers.md`. Record as `model` the one the CLI reports in its
   log header, never the model's own claim. Cursor reports none: record the model id you asked it for, noted as
   requested (workers.md). Send the CLI's full log outside the run dir and keep only its header there
   (workers.md, "Where a reviewer's log goes"): the log quotes test secrets and `fix publish` refuses it. Give it
   `references/passes/fix-review.md`. It answers three claims, each with evidence: `targeted`, `no_new_risk` and
   `minimal`. Record what it returns:
   `python3 <ia> finding set --run <run-dir> C-24 'fix.review={"model":"...","sha":"<HEAD>","claims":{...}}'`.
   - **All three CONFIDENT:** `fix done <id>`.
   - **Any other answer:** one revision round. The fixer amends its commit, then `fix check` again and a fresh review.
   - **Still not CONFIDENT:** set `fix.status=declined` with `fix.reason`, then `fix done <id>`. It resets the local
     branch, and nothing was pushed.
6. **Blocked.** The fixer stops without committing when a fix needs a design decision, a migration, an API contract
   change or another repo. Record that with `finding set C-24 fix.status=blocked 'fix.reason=...'`, then run
   `fix done <id>`.
7. **Publish.** `fix publish` writes `<run>/fix/commands.sh`. Every block in it:
   - pushes fast-forward only;
   - finds the open PR at run time;
   - rewrites the PR's **current** body: the draft note becomes the fix note, `Refs #N.` becomes `Closes #N.`, and
     everything else stays;
   - retitles the PR with the fix commit's subject and runs `gh pr ready`.

   A group PR is published only when every member is done or moot. `--partial` pushes what is fixed, keeps the draft
   and the title, and closes only the fixed members. The script works on the audited repo at the path in the manifest,
   never on a scratch clone. Show the person the script and tell them to run it themselves.

## Discipline

- **The red test is the spec, and it is frozen.** Never edit, skip, rename, weaken or delete a test from commit 1.
  Never add skip markers, and never change an expected value. `fix check` fails on any byte of it.
- **The fixer never judges its own fix.** A passing suite says the test is green, not that the cause is gone.
- **"No new failures" is a measurement:** the start's passing names compared with the check's. Never a rough count.
- **Blocked and declined are valid results.** Never widen the scope to get to green.
- **Closing an issue belongs to the PR body,** never to a commit. A squash or a cherry-pick would close it too early,
  so `fix check` fails on `Closes #N` in a commit.
- **Never push, edit a PR or mark it ready.** You write commands; the person runs them.

## Report to the person

For each PR branch:
- the PR number and its base;
- each member: `done` with the fix subject, `moot`, `blocked` or `declined` with the reason;
- the suite line from `fix check`, saying whether it was compared by names or by counts;
- the reviewer's model and claims;
- any conflict with the base;
- the path of `commands.sh`.

## References

- `references/passes/fix.md`: the fixer's pass.
- `references/passes/fix-review.md`: the reviewer's pass.
- `references/rules.md`: green for the right reason, scope, red flags.
- inherited-audit's `references/schema.md`: the `fix` fields of a finding, `sha_fix`, `tests[].green` and
  `fix.authorized_by`.
