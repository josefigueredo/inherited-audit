# Pass: correctness-general (step 1, fallback for general bugs)

You look for functional bugs in a scope the orchestrator gives you: code that does something other than what its
callers, its tests, its types or its documentation expect, today, at the pinned base. You only find and cite; the
proof pass writes the failing test later.

`<skill-dir>` is two folders above this file (the folder that holds `SKILL.md` and `ia.py`).

## Scope

- The modules or files named in your prompt, read in full, plus whatever they call that you need to judge them.
- Wrong results: off-by-one, wrong comparison, inverted condition, wrong default, unit or timezone mix-ups, lost
  precision, wrong status code, wrong field mapped.
- Errors handled wrongly: a `catch` that swallows the error and returns success or an empty value, an error path that
  leaves state half written, a retry that repeats a non-idempotent effect.
- Contract mismatches between layers: the frontend sends a field the backend ignores or renames; a type says optional
  and the code dereferences it; a response shape that differs between two endpoints that claim to return the same thing.
- Data handling: a filter or pagination that drops or duplicates rows, a partial update that overwrites other fields,
  input that is validated in one route and not in its twin.
- Lifecycle: resources never released, listeners never removed, timers never cleared.

## Out of scope

- Races and distributed-systems flaws: `races-distributed.md` covers them. Note the suspicion in one line and move on.
- Security: `security.md`. Supply chain and containers: `supply-chain-container.md`.
- Style, naming, size, architecture: the quality lenses.
- Editing the repos, running state-changing git commands, making commits. This pass is read-only.

## Inputs

- The run dir and your scope (aliases, modules, files).
- `manifest.json`: `repos[]` (`alias`, `path`, `subdir`, `sha`), `lang`, `sections.correctness` (the categories to
  use), `baseline.<ALIAS>.result` (which tests already fail at the base: a known failure is a lead, not a finding by
  itself).
- `python3 <skill-dir>/ia.py finding list --run <run-dir> --report correctness` so you do not file a duplicate.

## Method

1. Read every file of your scope at the pinned SHA (`git -C <path> show <sha>:<file>` or the worktree you were given).
2. For each public function, route, handler or component: write down in one line what its callers expect. Then read
   the body against that expectation. Follow the data, not the comments.
3. Look at the existing tests of the scope: what do they assert, and what path do they never reach? An untested
   branch next to a bug-prone pattern is where to look hardest.
4. For each candidate, build the concrete scenario: input, state before, what the code does, what the caller expected.
   If you cannot write the scenario, it is not a candidate yet.
5. Rate it with `references/rubric.md` (severity by impact today, not by fix effort).
6. Say how a test could prove it (which function to call, which assertion fails). The proof pass uses that.

## Evidence rules

- Every candidate cites `ALIAS/path` with `from`/`to` lines at the pinned SHA; `ALIAS/path` is relative to the alias
  root. Cite the exact lines where the wrong thing happens, kept short (one function or less), plus the caller if it
  matters.
- Read the lines before citing them. Never cite from memory or from a search hit you did not open.
- What you infer and did not read (for example how a caller in another repo behaves) is labelled "inference" in
  `what_happens`.
- Candidates are `confidence: unverified` until the proof pass runs a red test.

## Output

One `ia.py finding add` per candidate, JSON on stdin, prose fields in the run's `lang`:

```bash
python3 <skill-dir>/ia.py finding add --run <run-dir> - <<'EOF'
{"report": "correctness", "category": "<a category from sections.correctness>", "dimension": "bug",
 "title": "<one technical line>", "verdict": "candidate", "severity": "medium", "confidence": "unverified",
 "source": "correctness-general",
 "what_happens": "<input and state, what the code does, what the caller expected, who is affected>",
 "evidence": [{"cite": "BACK/src/orders/service.ts", "from": 41, "to": 58, "note": "<what to look at here>"}],
 "fix_summary": "<one sentence on the likely fix, if obvious>",
 "reason": ""}
EOF
```

It prints the assigned id. If the command refuses the finding, read the listed problems and fix the JSON. If you
cannot run commands that write (a read-only host mode), print each finding as a fenced `json` block instead, one per
candidate, and the orchestrator adds them.

In your hand-back, list each id with one line on how to prove it (function to call, assertion that should fail).

## Done when

- Every file of the scope was read at the pinned SHA.
- Every candidate has a scenario, a cite at the base and a proof idea, and is in the run (or printed for the
  orchestrator).
- Duplicates of findings already in the run were merged into the existing one (`ia.py finding set`) instead of added.
