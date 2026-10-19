# Pass: security (step 1, Cursor and fallback)

You look for security flaws in the code: who can read or change what they should not, what leaks, and what an input
can make the system do. The findings go to a team that did not ask for this audit, so each one states the impact and
the mechanism, never a step-by-step exploit.

`<skill-dir>` is two folders above this file (the folder that holds `SKILL.md` and `ia.py`).

## Scope

The modules your prompt names (or the whole repo), covering:

- **Authentication:** how identity is established on every entry point (HTTP, websockets, workers acting for a user,
  internal endpoints); token validation (issuer, audience, expiry, algorithm); routes that skip the auth hook;
  anonymous or development bypasses that can be on in production.
- **Authorization:** object-level checks on every read and write (can user A read or change B's resource by id?);
  list endpoints that filter by owner; admin-only routes; checks done after the work instead of before; background
  jobs acting with more rights than the user who started them.
- **Injection:** SQL or query building with string concatenation, shell commands, template rendering, path traversal in
  file names, server-side request forgery through user-provided URLs, prompt injection reaching tools with side effects.
- **Secrets and data exposure:** secrets in code, logs, error messages or responses; stack traces to clients; personal
  data in logs; credentials sent in URLs; tokens stored where scripts can read them in the frontend.
- **Transport and browser:** CORS, cookies (`Secure`, `HttpOnly`, `SameSite`), CSRF on state-changing routes, missing
  security headers where the app sets its own.
- **Abuse:** missing rate limits or size limits on expensive or public routes, unbounded uploads or payloads.

## Out of scope

- Dependency vulnerabilities, lockfiles, images and CI: `supply-chain-container.md`.
- Non-security bugs and races, unless the race is itself the security hole (then file it here with `dimension:
  "security"` and say so).
- Exploitation recipes, proof-of-concept payloads against real deployments, contacting any running system. Read code
  only. Editing the repos and making commits are out: this pass is read-only.

## Inputs

- The run dir and your scope.
- `manifest.json`: `repos[]` (`alias`, `path`, `subdir`, `sha`), `lang`, `sections.correctness`, `tools` (if `semgrep`
  or `gitleaks` ran, read their saved output under `outputs/` instead of repeating them).
- `python3 <skill-dir>/ia.py finding list --run <run-dir> --report correctness` to avoid duplicates.

## Method

1. Read the code at the pinned SHA (`git -C <path> show <sha>:<file>` or the worktree you were given).
2. Build the route table: every entry point with its auth requirement and the authorization check it performs. A table
   makes the missing check visible.
3. For each route that takes an id, follow it to the query: is the owner, tenant or role checked before the data is
   returned or changed?
4. Follow every user-controlled input to where it is used (query, shell, file system, outbound URL, template, model
   prompt with tools).
5. Search for secrets by shape and by name (`rg -n -i 'secret|token|password|api[_-]?key'`, long base64 or hex
   strings), and read the logging calls on auth and error paths.
6. For each candidate, write who can trigger it (anonymous, any logged-in user, a member of another tenant) and what
   they get (read, change, delete, run).
7. Rate with `references/rubric.md`: exposing data or credentials to the wrong people is high.
8. Say how a test could prove it (for example: call the route as user B with A's id and assert 403/404).

## Evidence rules

- Cite the missing or wrong check at the pinned SHA (`ALIAS/path`, `from`/`to`, relative to the alias root), plus the
  route registration that exposes it.
- Read every cited line. A protection you think a framework adds by default is checked against the version in the
  lockfile; otherwise label it "inference".
- If a control may live outside the repo (gateway, WAF, identity provider configuration), say "not visible from this
  repository" instead of "missing" (`references/verification-rules.md`, rule 1).
- Never copy a real secret into a finding, a note or your hand-back. Name the file and line and say "a credential is
  committed here"; mask any value.
- Candidates are `confidence: unverified` until the proof pass reproduces them.

## Output

One `ia.py finding add` per candidate, JSON on stdin, prose fields in the run's `lang`:

```bash
python3 <skill-dir>/ia.py finding add --run <run-dir> - <<'EOF'
{"report": "correctness", "category": "<a category from sections.correctness>", "dimension": "security",
 "title": "<one technical line>", "verdict": "candidate", "severity": "high", "confidence": "unverified",
 "source": "security",
 "what_happens": "<who can trigger it, what they can read or change, under which conditions; impact, no exploit steps>",
 "evidence": [{"cite": "BACK/src/documents/routes.ts", "from": 120, "to": 134, "note": "reads by id without an owner check"}],
 "fix_summary": "<the check to add, in one sentence>"}
EOF
```

If you cannot run commands that write (a read-only host mode), print each finding as a fenced `json` block instead and
the orchestrator adds them. The hand-back includes the route table and one line per id on how to prove it.

## Done when

- Every entry point of the scope is in the route table with its auth and authorization status.
- Every candidate names who can trigger it and what they get, cites the base, and has a proof idea.
- No secret value appears anywhere you wrote.
