# Pass: quality-lenses (step 2, `quality`)

You review code quality and architecture with four lenses, plus two dimensions that cut across them (operational
resilience and documentation that says something the code does not do). Every finding comes with a concrete
suggestion and, when it is quantitative, a number measured with a tool. The quality report only suggests; nothing here
changes the code.

`<skill-dir>` is two folders above this file (the folder that holds `SKILL.md` and `ia.py`).

## Scope

The orchestrator runs one subagent per lens and tier (it names yours in the prompt):

1. **Backend architecture:** module boundaries and coupling between domains; layering (routes, services, repositories:
   is it respected, is there business logic in routes or data access in routes); dependency injection versus `new`
   inside services; configuration and environment handling; error-handling strategy (swallowed errors, fallbacks that
   hide failures); cross-cutting concerns (auth, logging, timeouts, rate limits); duplicated route registration or API
   versions; persistence design (schema, migrations, seeds); background processing design (durability, retries,
   concurrency); where prompts and configuration live; provider abstractions; integration client design; testability.
2. **Backend code:** god files and god functions (measure the longest); duplication across similar modules; escape
   hatches from the type system (`any`, unchecked casts, non-null assertions) with counts; magic numbers and strings;
   naming consistency; dead or commented-out code and TODOs; errors swallowed (`catch {}`, `.catch(() => [])`); logging
   consistency; lint and compiler strictness; large modules without tests; data hard-coded in code.
3. **Frontend architecture:** framework usage (client versus server rendering, layouts, routing, data fetching); state
   management (size and responsibilities of global stores and hooks, prop drilling); the API layer (one giant client,
   error handling, token handling, polling); types versus the API contract (duplication, no shared schema); container
   and presentational separation; folder structure; styling architecture (one huge global stylesheet, design tokens);
   auth guards; environment configuration; build and lint strictness; test infrastructure; i18n; accessibility
   patterns.
4. **Frontend code:** giant components (measure lines and the number of state and effect hooks); components that fetch,
   hold state and render at once; duplicated markup and logic; casts and lint suppressions with counts; effects with
   missing dependencies or used for derived state; huge inline handlers; hard-coded copy; dead code and console
   logging; CSS quality (duplicated rules, `!important` count, hard-coded colours versus variables); markup
   accessibility (buttons without labels, clickable `div`s); form handling.

Every lens also reports, where its tier has them:

- **Resilience** (`dimension: "resilience"`): liveness and readiness probes and what they check; timeouts on every
  outbound call; graceful shutdown and drain windows (in-flight requests and jobs on `SIGTERM`); retries with backoff
  and limits; correlation or request ids carried through logs and outbound calls.
- **Lying documentation** (`dimension: "docs"`): README, `AGENTS.md`, `CLAUDE.md`, comments, OpenAPI specs or setup
  guides that describe paths, commands, variables or behaviour the code at the base does not have. Check each claim
  against the code before filing it.

## Out of scope

- Functional bugs, races and security flaws: they belong to the correctness report. If you see one, note it in one line
  for the orchestrator.
- Changing code, making commits, running state-changing git commands. This pass is read-only.
- Opinions without consequence ("I would name it differently"). Each finding needs a concrete effect on maintenance,
  evolution, reliability or onboarding.

## Inputs

- The run dir, your lens and tier, and the aliases in scope.
- `manifest.json`: `repos[]` (`alias`, `path`, `subdir`, `sha`), `lang`, `sections.quality`, `tools`,
  `baseline.<ALIAS>.plan.measure` (which measurement tools apply: dependency-cruiser, knip and jscpd for
  TypeScript/JavaScript, or the language's equivalents) and `baseline.<ALIAS>.result` (`coverage`).
- `python3 <skill-dir>/ia.py finding list --run <run-dir> --report quality` to avoid duplicates with the other lenses.

## Method

1. Read at the pinned SHA (`git -C <path> show <sha>:<file>` or a worktree at that SHA). Documentation in the repo may
   be out of date; when it disagrees with the code, the code wins and the disagreement may be a `docs` finding.
2. Measure before judging: line counts of the largest files and functions, counts with `rg -c`, and the measurement
   tools the person approved, run against a worktree at the pinned SHA. Save tool output under `<run-dir>/outputs/`.
   Use the tested commands in `references/workers.md` ("Measurement recipes"); a run that analysed 0 modules or 0
   files is a failed measurement, not a clean result. When a tool cannot be made to work, fall back to counting with
   `rg` (`rg -c 'pattern' <dir>`, `rg --files <dir> | wc -l`, `wc -l` on the largest files, `rg -n 'from .*\.\./'`
   for imports across module folders) and label the number "not measured with tools".
   For the counts below, use these exact regexes with `rg -c` (or `rg -n` to list the hits) over the alias root at the
   pinned SHA, so two runs count the same thing:

   | Regex | What it counts | Lens |
   |---|---|---|
   | `useState[<(]` | state hooks, typed or not (`useState(` alone misses `useState<T>(`) | frontend code |
   | `: any\b` | explicit `any` annotations | backend and frontend code |
   | `as Record<string, unknown>` | unchecked casts of untyped data | backend and frontend code |
   | `\.message\.includes` | error handling that branches on message text | backend code |
   | `\.slice\(0, \d+\)` | silent truncation with a magic length | backend and frontend code |
   | `role="dialog"` outside `ui/` (`-g '!**/ui/**'`) | hand-made dialogs that bypass the shared component | frontend code |
   | `<button` versus `<Button` | raw buttons against the design-system button, two counts | frontend code |
   | `console\.log` | stray console logging | backend and frontend code |
   | `'use client'` | client-rendered files (compare with the total files) | frontend architecture |
   | `process\.env` outside config (`-g '!**/config/**'`) | environment read outside the configuration module | backend and frontend architecture |

   Each finding that rests on one of these counts cites the regex it used in `measurement.tool` (for example
   `rg -c ': any\b' src`) and the total in `measurement.value`; per-file counts go to `<run-dir>/outputs/`.
3. Walk your lens's list. For each candidate, write why it matters in one to three sentences (a concrete consequence),
   and a concrete suggestion (target structure or a short sketch of at most ten lines).
4. Rate severity with `references/rubric.md` by its effect today, and effort as `S`, `M` or `L`.
5. Aim for up to 12 per lens, most severe first: fewer well-measured findings beat a padded list. Also collect what is done well, with cites, so the report is
   fair.

## Evidence rules

- Every finding cites `ALIAS/path` with `from`/`to` lines at the pinned SHA (relative to the alias root), verified by
  reading the lines.
- Every quantitative claim (lines, counts, duplication percentage, unused exports, cycles) carries `measurement` with
  the tool and the value. A number counted by reading, with no tool, is labelled "not measured with tools" in
  `measurement.tool`.
- Inferences are labelled "inference" in `what_happens`.
- A "missing" control (probes, timeouts, CI checks) is checked outside the code too: deployment manifests, CI,
  configuration (`references/verification-rules.md`, rule 1). If it may live elsewhere, write "not visible from this
  repository".

## Output

One `ia.py finding add` per finding, JSON on stdin, prose fields in the run's `lang`:

```bash
python3 <skill-dir>/ia.py finding add --run <run-dir> - <<'EOF'
{"report": "quality", "category": "<a category from sections.quality>", "dimension": "architecture",
 "title": "<one line>", "verdict": "confirmed", "severity": "medium", "confidence": "execution",
 "source": "quality-lenses",
 "what_happens": "<why it matters: the concrete consequence, one to three sentences>",
 "evidence": [{"cite": "BACK/src/bookings/service.ts", "from": 1, "to": 40, "note": "2900-line service mixes pricing, availability, payments and email"}],
 "suggestion": "<concrete change; target structure or a sketch of at most ten lines>",
 "effort": "L",
 "measurement": {"tool": "wc -l", "value": "2914 lines"}}
EOF
```

`dimension` is `architecture`, `code`, `resilience`, `docs` or `tests`. `confidence` is `execution` when a tool or a
command measured it, `docs` when you checked it against documentation, `unverified` when neither (those stay out of the
report). If you cannot run commands that write (a read-only host mode), print each finding as a fenced `json` block
instead and the orchestrator adds them.

The hand-back has a three-line summary of the tier and the list of things done well, each with its cite; the
orchestrator merges them into `strengths` with `ia.py set --run <run-dir> 'strengths=[...]'`.

## Done when

- Your lens's list was walked over the whole scope, plus resilience and documentation claims.
- Every finding has a cite at the base, a consequence, a suggestion, an effort, and a measurement or the
  "not measured with tools" label when it is quantitative.
- The hand-back has the summary and the strengths with cites.
