# Workers per host

The skill directs; workers do the work. Rule: use an external worker where a good one exists, the skill's own pass
prompt (`references/passes/<name>.md`) where none does. This table mirrors `ia/detect.py` `WORKERS`; `ia.py detect`
records it in `manifest.json` under `workers` and prints what is missing with its install command.

## How to use this table

- **Step 0 only, once:** list every row whose worker is missing for this host, with its exact install command, and ask
  the person one question: which ones to install. Never install anything without that answer. Rows they decline use
  the fallback pass for the whole run; do not ask again.
- `ia.py detect` can only test rows with a binary to look for (the scanners, `npx`, Cursor's `agent`). For plugin and
  slash-command rows it records `available: null`: check them yourself (is the slash command or skill listed in this
  session?) and include the missing ones in the same single question.
- The `measure` rows run through `npx -y`, which **downloads the package on first use**: that is installing. `detect`
  marks them `available: true` only when the package is already in `dependencies` or `devDependencies` of an audited
  repo's `package.json`; otherwise `null`, printed under "ask before using". Those always go into the one-time
  question; if the person declines, measure without them and label the numbers "not measured with tools".
- **Record what you checked:** `python3 <skill-dir>/ia.py set --run <run-dir> 'workers.<host>.<step>.<worker>.available=true'`
  (`false` when it is not there; JSON booleans only). `<step>` and `<worker>` are the exact strings of this table and
  of `manifest.workers.<host>`; an unknown host, step or worker is refused (exit 2). Several pairs go in one call and
  are saved together. It changes only `available`.
- An install command that starts with `/` is typed by the person in the host's prompt; it is not a shell command.
- "own pass" means there is no external worker: hand the pass file to a generic subagent.
- When a worker exists but produces nothing usable for a module, run the fallback pass on that module and record the
  pass name in the finding's `source`.

## Claude Code (`claude-code`)

| Step | Worker | Install (ask first) | Fallback pass |
|---|---|---|---|
| baseline | own pass | (none) | `references/passes/baseline-inventory.md` |
| correctness-bugs | /code-review per module | (built in) | `references/passes/correctness-general.md` |
| security | claude-security | `/plugin install claude-security@claude-plugins-official` | `references/passes/security.md` |
| races | own pass | (none) | `references/passes/races-distributed.md` |
| static | semgrep | `brew install semgrep` | `references/passes/supply-chain-container.md` |
| static | gitleaks | `brew install gitleaks` | `references/passes/supply-chain-container.md` |
| static | trivy | `brew install trivy` | `references/passes/supply-chain-container.md` |
| static | osv-scanner | `brew install osv-scanner` | `references/passes/supply-chain-container.md` |
| measure | dependency-cruiser | `npx -y dependency-cruiser --version` | (LLM measurement, labelled "not measured with tools") |
| measure | knip | `npx -y knip --version` | (same) |
| measure | jscpd | `npx -y jscpd --version` | (same) |
| unit-tests | superpowers:test-driven-development | `/plugin install superpowers@claude-plugins-official` | `references/passes/unit-tests.md` |
| e2e | Playwright | `/plugin install playwright@claude-plugins-official` | `references/passes/e2e-infra.md` |
| quality | feature-dev:code-architect | `/plugin install feature-dev@claude-plugins-official` | `references/passes/quality-lenses.md` |
| contrast | openai/codex-plugin-cc (/codex:adversarial-review) | `/plugin marketplace add openai/codex-plugin-cc && /plugin install codex@openai-codex` | `references/passes/contrast.md` |
| proof | own pass | (none) | `references/passes/red-test-proof.md` |
| verify | own pass | (none) | `references/passes/verify-high.md` |
| prose | own pass | (none) | `references/passes/owner-prose.md` |

Optional on Claude Code: `trailofbits/skills` as an extra security worker. Reference it, do not copy it (its licence is
CC-BY-SA-4.0).

## Cursor (`cursor`)

| Step | Worker | Install (ask first) | Fallback pass |
|---|---|---|---|
| baseline | own pass | (none) | `references/passes/baseline-inventory.md` |
| correctness-bugs | /review-bugbot | (built in when the account has it) | `references/passes/correctness-general.md` |
| security | own pass | (none) | `references/passes/security.md` |
| races | own pass | (none) | `references/passes/races-distributed.md` |
| static | semgrep | `brew install semgrep` | `references/passes/supply-chain-container.md` |
| static | gitleaks | `brew install gitleaks` | `references/passes/supply-chain-container.md` |
| static | trivy | `brew install trivy` | `references/passes/supply-chain-container.md` |
| static | osv-scanner | `brew install osv-scanner` | `references/passes/supply-chain-container.md` |
| measure | dependency-cruiser | `npx -y dependency-cruiser --version` | (LLM measurement, labelled "not measured with tools") |
| measure | knip | `npx -y knip --version` | (same) |
| measure | jscpd | `npx -y jscpd --version` | (same) |
| unit-tests | obra/superpowers | `/add-plugin superpowers` | `references/passes/unit-tests.md` |
| e2e | Playwright | (use the project's own Playwright, or add it to the tests branch) | `references/passes/e2e-infra.md` |
| quality | wshobson/agents (c4-architecture, comprehensive-review) | `/add-plugin (Cursor 2.5+ marketplace: https://github.com/wshobson/agents)` | `references/passes/quality-lenses.md` |
| contrast | agent -p --mode ask --model <other-model> --output-format json | (Cursor's `agent` CLI; nothing to install when it is on the PATH) | `references/passes/contrast.md` |
| proof | own pass | (none) | `references/passes/red-test-proof.md` |
| verify | own pass | (none) | `references/passes/verify-high.md` |
| prose | own pass | (none) | `references/passes/owner-prose.md` |

For the Cursor contrast row, `<other-model>` is a model of a different family from the one that wrote the findings, and
the prompt is the contrast pass with the run dir. `ask` mode is read-only, which is what the contrast needs. The same
invocation (with the model chosen for the pass) is how Cursor runs every **analysis pass** in a terminal: it keeps the
subagent read-only.

The wshobson/agents install is Cursor's own `/add-plugin` from the Cursor 2.5+ plugin marketplace (wshobson/agents,
`docs/harnesses.md`); `/plugin marketplace add` is the Claude Code command and does not apply here.

## Contrast through the Codex CLI

When the Codex plugin is not usable, the same model family can be reached with its CLI. The command that works
unattended is exactly:

```bash
codex exec -s read-only --skip-git-repo-check -o <file> "<prompt>" < /dev/null
```

- `< /dev/null` closes stdin. Codex prints "Reading additional input from stdin..." even with it (measured), then
  reads end of file and runs. That it blocks forever without it, when the host leaves stdin open, is how the first
  acceptance run failed; not re-measured here.
- `-s read-only` keeps it from editing; `--skip-git-repo-check` lets it run from a run dir that is not a repo;
  `-o <file>` writes the final answer to `<file>` (measured: `say ok` left `ok` in the file).
- The model name is **not** in `<file>`. It is in the log header Codex prints on stderr/stdout before the answer, the
  line `model: <name>`. Read it from there for `contrast.model`.

## Measurement recipes (tested)

Run from the root of the audited code (a worktree at the pinned SHA), with outputs under `<run-dir>/outputs/`. Each
recipe has a **success signal**; without it the measurement failed and the numbers are "not measured with tools",
never "nothing found". All three download packages through `npx -y`: only after the person agreed (see above).

**dependency-cruiser** (modules, dependencies, cycles):

```bash
npx -y -p dependency-cruiser -p typescript@5 depcruise --no-config --output-type json \
  --ts-config <tsconfig> --include-only '^<src-dir>' <src-dir> > <run-dir>/outputs/depcruise.json
```

- Success: `summary.totalCruised` in the JSON is greater than 0 (the `--output-type err` form prints
  `no dependency violations found (<N> modules, <M> dependencies cruised)`).
- **`0 modules cruised` is a failed measurement, never "no violations".** The usual cause is that dependency-cruiser
  found no TypeScript compiler (its JSON lists `.ts` as `available: false` and a `missing-typescript-transpiler`
  warning): the `-p typescript@5` above (the tested spec) supplies one when the repo has no `node_modules`. Other likely causes (inference, not measured) are an
  `--include-only` regex that does not match the paths as given (the paths are relative to the current directory, so
  `^<src-dir>` must start where the argument starts) and a wrong `<src-dir>`.
- Cycles: put `{"forbidden":[{"name":"no-circular","severity":"error","from":{},"to":{"circular":true}}]}` in a JSON
  file under `<run-dir>/outputs/` and replace `--no-config` by `--config <that file>`, with `--output-type err`.

**knip** (unused files, exports and dependencies):

```bash
npx -y knip --no-progress --reporter json > <run-dir>/outputs/knip.json
```

- It exits 1 when it reports issues; that is a result, not a failure. Success: the JSON `issues` array lists files
  and the sections you expect (`files`, `exports`, `dependencies`), or the default reporter prints
  `Unused files (<N>)`. An empty `issues` on a repo with a `package.json` and sources means it found no entry points:
  treat it as failed and say so.
- Without `node_modules`, knip also prints "Unlisted dependencies" and "Unlisted binaries" that come from the missing
  install, not from the code: do not report those as findings.

**jscpd** (duplication):

```bash
npx -y jscpd --min-tokens 50 --reporters console,json --output <run-dir>/outputs/jscpd <src-dir>
```

- Success: the table's `Files analyzed` is greater than 0; the cite is its `Clones found` and the duplicated-lines
  percentage (`<N> (<P>%)`). `Files analyzed 0` is a failed measurement.

When a recipe still fails, say so in `measurement.tool` ("not measured with tools") and use the `rg`-based fallback of
`references/passes/quality-lenses.md`.

## Models for the contrast

Pick a model of a **different family** from the author's (on Claude Code, Codex through the plugin; on Cursor, any
non-Claude model the account offers, or the reverse). When none is available the contrast still runs, with another
model of the same family (for example a larger one), and every finding it reviews gets `contrast.same_family=true`.
The quality report states which model contrasted which and whether they were of the same family.

## Hosts other than these two

`ia.py init` accepts `unknown`; `ia.py detect` then records both tables. Use the own passes for everything and the
scanners that are on the PATH.
