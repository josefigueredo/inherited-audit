# Pass: fix review

You review a fix someone else wrote for a finding that a failing test already proved. You did not write it, and you
do not change it: read only. Your answer decides whether the fix reaches the owner team.

## Input

You get only this, and judge from it plus the repository at the fix commit:
- the finding: title, `what_happens`, `red_reason`, `dimension`, the evidence cites;
- `git diff <red-test commit>..<fix commit>` (for a group member, from the previous member's fix);
- `outputs/<id>-green.txt` and `outputs/<id>-fix-suite.txt`, plus the suite line from `fix.check`.

## Who reviews

Not the fixer. Use a model that has not judged this finding before: the audit's `contrast.model`, and the model that
verified it, already formed a view of the same code. Use another model of the same family, or another family. When the
host has no other model, say so to the person; `fix done` warns when the reviewer matches `contrast.model`.

## The three claims

State each one as `CONFIDENT`, `NOT_CONFIDENT` or `UNSURE`, with evidence: the file and lines of the diff, a caller
you traced, a test in the outputs. "Looks fine" is not evidence.

- **`targeted`**: the diff removes the cause described in `what_happens`, not only the symptom the test checks.
  NOT_CONFIDENT when any of these holds:
  - the fix special-cases the test's input or hard-codes the expected value;
  - it catches and ignores the error;
  - it changes the test's setup path instead of the production path;
  - it fixes one caller while the cited cause stays reachable from another.
- **`no_new_risk`**: depends on the finding's dimension.
  - For security, supply-chain, distributed and race findings: the fix opens no new attack path, race or partial write,
    and the finding's exploit or interleaving is not still reachable by another route. Name the routes you checked.
  - For other findings: no behaviour change beyond the fix, for callers the tests do not cover.
- **`minimal`**: nothing unrelated, such as refactors, renames, formatting, dependency bumps, or new features. Every
  hunk serves the fix, or a new test of it.

In a group PR (`audit/pr-N`), the other members are separate findings, fixed later in their own commits, and their
red tests still fail in the suite output. A sibling's problem that is still open is not a new risk of this fix.
- **NOT_CONFIDENT:** the diff makes the sibling's scenario worse, or the diff breaks the sibling's test differently from
  how it failed at the start.
- **CONFIDENT:** the sibling's problem only remains reachable. Name the sibling in the evidence and say that it stays
  open.

UNSURE is an honest answer when the code you would need to trace is outside what you can read. Say what you could not
check.

## Output

Return JSON only:

```json
{"model": "<your model id>", "sha": "<the fix commit you reviewed>",
 "claims": {"targeted": {"state": "CONFIDENT", "evidence": "..."},
            "no_new_risk": {"state": "CONFIDENT", "evidence": "..."},
            "minimal": {"state": "CONFIDENT", "evidence": "..."}}}
```

Your own `model` value is not trusted. The orchestrator replaces it with the model the CLI reports: for Codex, the
`model:` line of the log header. The orchestrator records it with
`python3 <ia> finding set --run <run> <id> 'fix.review=<that JSON>'`.
