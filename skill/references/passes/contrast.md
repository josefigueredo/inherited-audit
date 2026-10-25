# Pass: contrast (fallback contrast in a fresh subagent)

You are a second opinion from a different model. You did not find these problems and you have not seen how anyone
reasoned about them: you get each finding's JSON and the code it cites, and you decide on your own whether the code
supports it. Disagreeing is useful; agreeing by default is not.

`<skill-dir>` is two folders above this file (the folder that holds `SKILL.md` and `ia.py`).

## Scope

- Every finding the orchestrator names (by default all findings of the run that are not `discarded`), both reports.
- For each: does the cited code at the pinned base do what `what_happens` says; is the severity right by
  `references/rubric.md`; for quality findings, is the suggestion sound and the measurement plausible.

## Out of scope

- The first agent's reasoning, notes, transcripts or hand-backs. If the orchestrator pasted them into your prompt,
  ignore them and say so in your hand-back.
- Finding new problems. If you see one, mention it in one line in the hand-back; do not file it.
- Editing the repos, running tests, making commits, changing any field other than `contrast.*`. This pass is read-only.

## Inputs

- The run dir and the model you are running as (the orchestrator tells you; you need it for `contrast.model`), plus the
  model family that wrote the findings, so you can set `contrast.same_family`.
- `manifest.json`: `repos[]` (`alias`, `path`, `subdir`, `sha`), `lang`.
- For each finding, only `findings/<id>.json` fields `id`, `report`, `dimension`, `title`, `severity`, `what_happens`,
  `evidence`, `suggestion`, `measurement`, and the code at the cites. `python3 <skill-dir>/ia.py finding list --run
  <run-dir>` lists them.

## Method

1. For each finding, read the cited lines at the pinned SHA (`git -C <path> show <sha>:<file>`), plus enough around
   them to understand the code path (the caller, the function it calls). `ALIAS/path` is relative to the alias root.
2. Try to break the claim: is there a check elsewhere that prevents it, a transaction one level up, a framework default,
   a caller that never passes that input, a test that already covers it?
3. Decide:
   - `agree`: the code supports the claim and the severity is right or close;
   - `refute`: the code does not support it (the guard exists, the path is unreachable, the cite is wrong, the
     measurement is wrong), or the severity is off by more than one level;
   - `unsure`: you could not decide from the code alone (it depends on runtime configuration or on code outside the
     repos).
4. For every `refute`, say what you refute with `contrast.scope`: `contrast.scope=severity` when the finding is real but the severity
   is off (you say the level it should be in the note), `contrast.scope=finding` when the claim itself does not hold. A `scope=severity`
   refute does not hide the finding; a `scope=finding` one does, unless the orchestrator rebuts it.
5. Write a note of one to three sentences for every verdict, with a cite when you point at code the finding missed.

## Running it through a CLI

On Claude Code without the Codex plugin, the orchestrator reaches Codex with exactly this command (the
`< /dev/null` stops it waiting on stdin):

```bash
codex exec -s read-only --skip-git-repo-check -o <file> "<prompt>" < /dev/null
```

The answer is in `<file>`; the model name is the `model:` line of the log header Codex prints, not part of `<file>`.
Cursor's `agent` prints no model: record the `--model` id you passed, with the note
`(requested; Cursor does not report it)`.
On Cursor: `agent -p --mode ask --trust --workspace <dir> --model <other-model> --output-format json`. Details, and
where the full log goes: `references/workers.md`.

## Evidence rules

- A `refute` cites the code that contradicts the finding (`ALIAS/path:from-to` in the note) or names exactly what is
  wrong with the finding's own cite.
- Do not refute on style or wording. Refute on facts.
- What you infer is labelled "inference" in the note.

## Output

One `ia.py finding set` per finding, with the note in the run's `lang`:

```bash
python3 <skill-dir>/ia.py finding set --run <run-dir> C-07 contrast.model=<your model> contrast.same_family=false \
  contrast.verdict=refute contrast.scope=finding 'contrast.note=<one to three sentences, with the cite that contradicts it>'
```

`contrast.scope` is `severity` or `finding` on every `refute` and stays empty otherwise. Never set `contrast.rebutted`
or `contrast.rebuttal`: only the orchestrator does, after checking your refute against the code; it writes its answer
in `contrast.rebuttal` and leaves your note as it is, and the report prints both.

`contrast.same_family` is `true` when you are the same model family as the one that wrote the findings (the
orchestrator could not get a different family); the reports say so. `contrast.verdict` is `agree`, `refute` or
`unsure`. If you cannot run commands that write (a read-only host mode, for example Cursor's `agent -p --mode ask`),
print one line of JSON per finding instead and the orchestrator applies them:

```json
{"id": "C-07", "contrast": {"model": "<your model>", "same_family": false, "verdict": "refute", "scope": "finding", "note": "..."}}
```

The hand-back counts agree, refute and unsure, lists every refute with its note, and names any new problem you noticed
in one line each.

## Done when

- Every finding in scope has `contrast.model`, `contrast.same_family`, `contrast.verdict` and a note, and every `refute` has `contrast.scope`.
- Every `refute` points at the code or the cite that contradicts the finding.
- You never read the first agent's reasoning.
