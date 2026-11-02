# Host modes: when the host cannot do everything

Two situations change who does each pass, never whether the audit runs. Read the section that applies when SKILL.md
sends you here; on a host that launches subagents and lets them write, you do not need this file.

## No subagents on this host

Some hosts or sessions cannot launch subagents (no agent tool, or a mode that forbids it). The audit still runs; only
who does each pass changes. Tell the person once, at step 0, and say it again in "Finishing".

- **Run the passes yourself, sequentially, module by module, driven by the coverage map.** Take the first open cell
  from `python3 <skill-dir>/ia.py coverage status --run <run-dir>`, read that pass file, run it on that one module,
  record the cell with `ia.py coverage add`, and take the next. For `races-distributed`, walk the ten topics with the
  pass's starting searches on the module before recording it with `--topics`. Finish a module before opening the
  next, so a time-box leaves whole modules done rather than every module half done.
- When the time does not reach, say how many cells are left and let the person decide; only they can close with
  `--force-open "<reason>"`.
- **Writing passes** (proof, unit-tests, e2e-infra) run one at a time, still each in its own worktree, removed when done.
- **verify:** the judgment comes from a **different model** through a read-only CLI (the contrast rows of
  `references/workers.md`: Cursor's `agent` CLI in ask mode, or the read-only Codex CLI recipe there), given
  only the verify-high pass, the finding files, the branches and the run dir. A read-only CLI cannot run tests, so
  you, the orchestrator, rerun them in a throwaway worktree and record them as rerun by the orchestrator in
  `outputs/<id>-verify.txt`; the verifier judges that output. `references/passes/verify-high.md` has the details.
- **contrast** still uses a model of another family from the author's, as in its step, and preferably not the
  model that did verify, so each check comes from fresh eyes.

## A pass prints JSON blocks instead of writing

When a pass prints JSON blocks instead of writing (a read-only host mode, such as Cursor's agent CLI in ask mode), you
apply them. Save each finding block to its own file and run `ia.py finding add --run <run-dir> <file>`. A contrast
line `{"id": "C-07", "contrast": {...}}` becomes one call:
`ia.py finding set --run <run-dir> C-07 contrast.model=<model> contrast.same_family=<true|false>
contrast.verdict=<agree|refute|unsure> 'contrast.note=<note>'`. Then check them with `ia.py finding list`.
