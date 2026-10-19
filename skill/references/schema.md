# Schema

A run is a directory outside the audited repos with `manifest.json` (the resumable state), `findings/<id>.json` (one
file per finding) and `outputs/` (raw command output). Every worker writes findings in this one shape, so the filter
and the render never depend on who found what. `ia/findings.py` validates it on `ia.py finding add` and
`ia.py finding set`; an invalid finding is refused with every problem listed (exit 1).

## Path bases (read this first)

Two different bases are used, on purpose:

| Field | Base | Example |
|---|---|---|
| `evidence[].cite` | `ALIAS/path`, where `path` is relative to the **alias root** = the repo top level joined with the repo's `subdir` | `BACK/src/orders/service.ts` |
| `tests[].path` | relative to the **repo top level** (what git uses) | `api/tests/orders/test_race.py` |
| `prod_files[]` | relative to the **repo top level** | `api/src/orders/service.ts` |

So with `--repo BACK=/w/repo:api`, the same file is cited `BACK/src/x.py` and listed as `api/src/x.py`. Cites are
checked against the pinned SHA by `ia.py cite-check`; test paths and production files feed `git diff` and the publish
bodies, which run at the top level.

**`ROOT` alias.** When every alias of a repo has a `subdir` (a monorepo audited by folders), `ia.py init` adds the
alias `ROOT` (`ROOT2`, ... if the name is taken) with an empty `subdir`, so root-level files are citable:
`ROOT/Dockerfile`, `ROOT/entrypoint.sh`, `ROOT/.github/workflows/ci.yml`. `ROOT` has no baseline and `detect` lists
as its modules only `.` (the files sitting directly at the repo root, when there are any) and the root-level
directories no other alias covers (`.github`, `docker`, `deploy`, `infra`, `scripts`, those that exist). Its modules
need only the `security` and `quality-lenses` coverage cells.

**History cites.** A cite may end in `@<7-40 hex commit>`: `BACK/src/.env@3f9a1c2`. `cite-check` resolves the path and
the lines **at that commit** and requires it to be an ancestor of (or equal to) the base SHA. The report prints the
path and «en el historial (commit 3f9a1c2)»; when the finding's `dimension` is `security` or `supply-chain` it prints
**no snippet at all** (the lines may hold a secret); for any other dimension it prints the masked snippet at that commit.
`eval` compares cites by path and ignores the `@commit`.

**Secrets that exist only in history** are filed as `dimension: security`, `confidence: execution`,
`measurement.tool: "gitleaks detect ..."` (the exact command, with `--redact`), `measurement.value` the rule id and
the count, `outputs.suite` the redacted output saved under `outputs/`, and an evidence cite with `@commit` on the file
where it was added. No branch or red test is needed (see the non-code rule below). The value is never written: not in
`what_happens`, not in `measurement`, not in a note. For example (`ia.py finding add` assigns the id):

```json
{"report": "correctness", "category": "secrets", "dimension": "security", "verdict": "confirmed",
 "severity": "high", "confidence": "execution", "source": "gitleaks",
 "title": "An AWS access key committed in history is still readable",
 "what_happens": "An access key was committed and later deleted; anyone who can clone the repo can still read it.",
 "measurement": {"tool": "gitleaks detect --redact --log-opts=--all", "value": "aws-access-token: 1"},
 "outputs": {"red": "", "green": "", "suite": "outputs/gitleaks-BACK.txt"},
 "evidence": [{"cite": "BACK/.env@3f9a1c2", "from": 1, "to": 1, "note": "value redacted"}]}
```

## Finding

Ids: `C-NN` for the correctness report, `Q-NN` for the quality report. `ia.py finding add` assigns the next free id
when the JSON has none, and prints it.

### Always required

| Field | Values |
|---|---|
| `id` | `C-07`, `Q-03` (prefix must match `report`) |
| `report` | `correctness` or `quality` |
| `category` | a category of this audit, chosen in step 0 from the system's domains (not a fixed list) |
| `dimension` | `bug`, `race`, `distributed`, `security`, `supply-chain`, `container` (correctness); `architecture`, `code`, `resilience`, `docs`, `tests` (quality) |
| `title` | one line, technical |
| `verdict` | `candidate`, `confirmed`, `discarded`, `blocked` |
| `severity` | `high`, `medium`, `low` (see `references/rubric.md`) |
| `confidence` | `execution`, `docs`, `unverified` |
| `source` | the worker or pass that found it, e.g. `races-distributed`, `/code-review`, `semgrep` |
| `what_happens` | what goes wrong, for whom, under which conditions; inferences labelled as such |
| `evidence` | at least one `{"cite": "ALIAS/path", "from": 10, "to": 24, "note": "..."}`; `from`/`to` are 1-based lines at the base SHA |

### Required when `verdict` is `confirmed`, `report` is `correctness` and `confidence` is `execution` (code dimensions)

Applies to every correctness finding except those proven by a command (next table).

| Field | Meaning |
|---|---|
| `branch` | local branch of this finding (no upstream) |
| `sha_test` | the commit with only tests (red at the base) |
| `tests` | at least one `{"path": "...", "red": "3 of 3 fail", "green": "", "note": ""}` |
| `red_reason` | the assertion that fails at the base and why that is the problem, not a setup error |

### Required when `verdict` is `confirmed`, `confidence` is `execution` and the proof is a command

This rule applies when `dimension` is `supply-chain` or `container`; or when `dimension` is `security` and every
`evidence[].cite` carries `@commit` (a secret only in history); or when `dimension` is `security` and
`measurement.tool` is set (configuration, CI or secrets verified by a scanner). No code test can express these, so no
branch is needed; the proof is the command that was run and its saved output.

| Field | Meaning |
|---|---|
| `measurement.tool` | the command that was run (scanner, floor install, image build, lookup), e.g. `osv-scanner --lockfile package-lock.json` |
| `outputs.suite` | the raw output saved under `outputs/`, e.g. `outputs/osv-BACK.txt`; or, instead, an `evidence[].note` that names that `outputs/` file |

A `confirmed` one with `docs` confidence needs neither. `unverified` ones stay `candidate` and out of the reports.

### Required when `report` is `quality`

| Field | Meaning |
|---|---|
| `suggestion` | what to change, concretely |
| `effort` | `S`, `M` or `L` (see the rubric) |

### Optional (defaults filled in by `ia.py finding add`)

| Field | Meaning |
|---|---|
| `reason` | why it was discarded or blocked |
| `fix_summary` | the written proposal: one or two sentences on how to fix it (the skill never applies it) |
| `measurement` | `{"tool": "jscpd", "value": "14% duplicated lines"}` for quantitative quality findings |
| `base` | the branch or SHA the finding branch starts from, when it is not the pinned base (stacked branches) |
| `sha_fix` | legacy: kept in the schema, ignored by render and publish; never required and never written |
| `prod_files` | production files the proposal touches (top-level relative); publish uses them to group PRs |
| `outputs` | `{"red": "outputs/C-07-red.txt", "green": "", "suite": ""}`: raw output saved in the run dir. `red` is the red-test output of each code finding; `suite` is only for supply-chain, container and command-proven security findings (the command's output). `green` and a per-finding `suite` for code findings are legacy (kept, never written) |
| `contrast` | `{"model": "...", "same_family": false, "verdict": "agree", "scope": "", "rebutted": false, "note": "...", "rebuttal": ""}`; `verdict` is `agree`, `refute`, `unsure` or empty. `scope` (only meaningful on `refute`) is `severity` (the finding is real, the severity is wrong: you lower it and the finding stays visible), `finding` (the finding itself does not hold) or empty (old data: treated as `finding`). `rebutted` is `true` when you checked a `finding` refute against the code and it does not hold: the finding stays visible. `note` is the contrast model's note and is never overwritten; `rebuttal` (a string, masked like prose) is the orchestrator's answer, and the report prints both (an old rebutted finding with an empty `rebuttal` prints `note` as the rebuttal). Old findings without `scope`, `rebutted` or `rebuttal` still load and validate |
| `exclude` | `refactor`, `feature`, `tooling`, `doubtful`, `no-code` or empty (correctness only; see the rubric) |
| `shown` | set by `ia.py filter`: `true` when the finding goes into its report; never set it by hand |
| `audience` | `{"title": "", "what_happens": "", "fix_summary": ""}`: owner-team prose written in step `prose`; the reports prefer it over the technical fields |

Change fields with dotted keys and JSON values, for example
`ia.py finding set --run DIR C-07 contrast.model=<model> contrast.verdict=agree contrast.same_family=true`.

## manifest.json

Written by `ia.py init` and kept by every command. Fields the skill reads or fills:

| Key | Written by | Meaning |
|---|---|---|
| `version` | init | schema version; a newer one is refused |
| `system`, `lang`, `host`, `created` | init | `lang` is the report language (default `es`) |
| `options` | init | `{"fix": false, "publish": false}`; `fix` is always `false` (an old `true` loads as `false` with a warning) |
| `repos` | init | `[{"alias", "path" (repo top level), "subdir", "sha" (pinned base), "remote"}]` |
| `steps` | `ia.py step`, baseline, filter, render | state of each step: `pending`, `in_progress`, `done`, `skipped` |
| `tools`, `workers` | detect | which tools are on the PATH; the worker table per host |
| `baseline.<ALIAS>.plan` | detect; edited with `ia.py baseline --set` | `stack`, `test_cmd`, `coverage_cmd`, `measure`, `measured`, `env`, `pre`, `deps`, `deps_dirs`, `install_cmd`, and `edited` (the keys `baseline --set` changed; a later `detect` keeps them) |
| `baseline.<ALIAS>.result` | baseline | `passed`, `failed`, `total` (from `test_cmd`), `coverage` (from `coverage_cmd`, run as a separate step, and only when the suite parsed with `failed == 0`; otherwise `coverage_error` is `skipped: suite failing`; any other failure is `coverage_error` too and keeps the counts), `runner`, `exit_code`, `output` (raw file under `outputs/`), `timed_out`, `measured`, `source` (`manual` once numbers were recorded with `ia.py set`; absent for a run result), `parsed` (`false` when the suite ran but its summary could not be read: the step stays open until you record the numbers), `error` |
| `baseline.<ALIAS>.tests_branch` | `ia.py set` | name of the step-1.5 branch with tests that prove no bug (missing coverage, e2e, infrastructure); merge-check and hygiene include it |
| `modules` | detect | `{"BACK": ["src/.", "src/lib", "src/modules/orders"]}`: module paths per alias, relative to the alias root, sorted; `src/.` (or `.`) is the pseudo-module of the files sitting directly in that folder |
| `coverage` | `ia.py coverage add` | `{"<pass>": {"BACK/src/lib": {"result": "found\|nothing", "topics": [1, 2], "note": ""}}}`; passes: `correctness-general`, `races-distributed`, `security`, `quality-lenses`; `topics` is required (1 to 10, all of them) for a complete `races-distributed` cell; modules of a `root: true` alias need only `security` and `quality-lenses` |
| `coverage_waivers` | `ia.py step ... done --force-open` | `[{"step": "correctness", "reason": "...", "open": ["BACK/src/lib / security"]}]`; shown in "How it was done" |
| `sections.correctness`, `sections.quality` | `ia.py set` | ordered list of category names; the reports show categories in this order (unlisted ones go after) |
| `strengths` | `ia.py set` | list of strings for "What is done well"; omit or leave empty to skip the section |
| `author_model` | `ia.py set` | the model that wrote the findings; "How it was done" states it next to each contrast model |
| `filter` | filter | `{"counts": {...}, "start_here": ["Q-03", ...]}` |

Never edit `manifest.json` by hand. Manifest-level keys go through `ia.py set --run DIR KEY=VALUE...` (JSON values,
or the raw string when the value is not JSON; every pair is checked before one atomic save):

| Key | Value |
|---|---|
| `host` | `claude-code`, `cursor` or `unknown` (then run `ia.py detect` again) |
| `lang` | report language, a non-empty string |
| `options.publish` | `true` or `false` |
| `sections.correctness`, `sections.quality` | list of strings |
| `strengths` | list of strings |
| `author_model` | the model that wrote the findings, a non-empty string (taken as a string) |
| `baseline.<ALIAS>.tests_branch` | branch name, taken as a string (`2024` stays `"2024"`); the alias must be one of the run's repos |
| `baseline.<ALIAS>.result.passed`, `.failed`, `.total` | integer >= 0 (a repo with no runner records `total=0`) |
| `baseline.<ALIAS>.result.coverage` | number 0 to 100, or `null` |
| `baseline.<ALIAS>.result.runner` | string; `.measured`: `true` or `false` |

Setting any `result.*` key marks `result.source = "manual"`; the `baseline` step closes once every repo has a parsed or manual result. `lang` and `author_model` are also taken as strings.

For example `ia.py set --run DIR host=cursor 'strengths=["Clear boundaries (BACK/src/app.ts:1-20)"]'`. Plan keys go
through `ia.py baseline --set`; finding fields through `ia.py finding set`.

## outputs/

Raw output of every command whose result a finding relies on: `baseline-<ALIAS>.txt` (written by `ia.py baseline`),
the red-test output of each code finding (`<id>-red.txt`), and the command output of each supply-chain, container or
command-proven security finding (`outputs.suite`). Green and per-finding full-suite runs are legacy: nothing writes
them now. Save every file with secrets masked; `ia.py hygiene` scans this folder and `findings/`.
