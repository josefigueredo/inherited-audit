# Rubric

One rubric for every worker and every pass, so the filter and the reports do not depend on who found what. The
reports print the severity rule below word for word (`ia/render.py`, `rubric` label); keep both in step.

## Severity

Pick the highest level whose description fits what happens **today, at the pinned base**, not what could happen after
other changes.

- **High:** exposes data or credentials to the wrong people, corrupts data, or breaks a whole feature.
- **Medium:** a visible wrong result, or minor information exposure.
- **Low:** robustness, observability or a visible inconsistency without loss.

Rules of application:

- Severity is about impact, not about how hard the fix is (that is effort) or how sure you are (that is confidence).
- When two levels fit, pick the higher one and say in `what_happens` which condition makes it that bad.
- A race or distributed-systems flaw is rated by what it does when it fires (lost write = corrupts data), not by how
  often you think it fires; the frequency goes in the prose as an inference.
- Every `high` is re-verified outside the agent that found it (step `verify`) before it can be shown.

## Confidence

| Value | Meaning | Shown in a report? |
|---|---|---|
| `execution` | Reproduced by running something: a red test at the base, a command, a build, a request. | yes |
| `docs` | Verified against authoritative documentation or the tool's own API (a registry, a release page), not run. | yes |
| `unverified` | Plausible, but nothing confirmed it. | no: tell the person, keep it in the data |

A correctness finding about code needs `execution` (a red test). Configuration, container, CI and supply-chain findings
may stop at `docs` when no test can express them; apply `references/verification-rules.md` before choosing. A
`supply-chain` or `container` finding, or a `security` one verified by a scanner (`measurement.tool`) or present only
in history (every cite with `@commit`), reaches `execution` by running a command (scanner, build, floor install) and
saving its output, not with a red test (`references/schema.md`).

## Effort (quality report)

- **S:** a small local change.
- **M:** touches several files.
- **L:** means redesigning a part.

"Start here" in the quality report sorts shown findings by severity, then effort, so a `high`/`S` comes first.

## Dimensions

| Report | Dimensions |
|---|---|
| correctness | `bug`, `race`, `distributed`, `security`, `supply-chain`, `container` |
| quality | `architecture`, `code`, `resilience`, `docs`, `tests` |

`supply-chain` covers lockfiles, hashes, mutable references and SBOMs; `container` covers image hardening; `resilience`
covers probes, timeouts, drain windows and correlation ids in logs; `docs` covers documentation that says something the
code does not do.

## Exclusions (correctness report)

Set `exclude` when a correctness finding, even if true, does not belong in the owner team's report:

| Value | When |
|---|---|
| `refactor` | The fix needs a refactor. |
| `feature` | It asks for new functionality, not a correction. |
| `tooling` | CI, build or local tooling. |
| `doubtful` | The evidence is not conclusive. |
| `no-code` | It was closed without a code change. |

`exclude=duplicate` is the one value that also applies to quality findings: the finding repeats another one, named in
`duplicate_of` (same report). It is merged, not discarded: the reports count it apart.
