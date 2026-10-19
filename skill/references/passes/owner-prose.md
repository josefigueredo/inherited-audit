# Pass: owner-prose (step `prose`)

You write, for every finding that will be shown, the text the owner team reads. They did not ask for this audit, they
know their system better than anyone, and they will look for any weak point. The report already shows them the cites,
the branch, the commit with the red test and the red output; you write the prose around it. Describe
behaviour, not people.

`<skill-dir>` is two folders above this file (the folder that holds `SKILL.md` and `ia.py`).

## Scope

Every prose field the reports render, for every finding with `shown: true`, in the run's `lang` (from
`manifest.json`):

- `audience.title`, `audience.what_happens` and `audience.fix_summary`, which you write;
- `red_reason`, `tests[].note` and `evidence[].note`, which the reports show as they are: you rewrite their prose when
  it carries audit jargon, blame or another language. Prose only: code facts, paths, numbers, line ranges, test
  counts and quoted assertion messages stay exactly as they are.
- Only from what the finding already holds (`title`, `what_happens`, `fix_summary`, `suggestion`, `red_reason`,
  `tests[].note`, `reason`, `contrast.note`, `contrast.rebuttal`, `measurement`) and the raw outputs it points to. Invent nothing.

## Out of scope

- Changing any technical fact: severity, verdict, `title`, `what_happens`, cites, `from`/`to`, `tests[].path`,
  `red`/`green` counts, SHAs, measurements. If a fact looks wrong, tell the orchestrator.
- Findings with `shown: false`.
- Editing the repos or making commits.

## Inputs

- The run dir.
- `manifest.json`: `lang`, `system`, `repos[]` (aliases), `filter` (the shown ids).
- `python3 <skill-dir>/ia.py finding list --run <run-dir>` and each `findings/<id>.json`; the raw outputs under
  `outputs/` that a finding points to.

## Method

1. **Reader and tone.** A senior developer of the owner team. Technical, neutral, no adjectives, no selling. Say what
   the code does today at the base, what happens and to whom, and what changes with the fix.
2. **No blame.** Nothing like "nobody noticed", "badly done", "careless", "obviously". No authors, no history of who
   wrote what.
3. **No internal jargon of the audit.** The reader does not know the process. Do not use its phrases: pass and step
   names ("red-test-proof", "quality lens", "contrast pass", "baseline step"), "candidate", "red for the right
   reason", "fresh subagent", finding sources, internal ids of documents they never saw, or the names of any agent,
   session or model. Ordinary domain words are fine when they mean the system's own things: a queue "worker", a
   performance "baseline", a colour "contrast". Finding ids that appear in the report (`C-07`, `Q-03`) may be cited; ids of findings not shown may
   not.
4. **Security:** impact and mechanism yes; exploitation steps, payloads or a recipe no.
5. **Inferences are labelled.** Anything that was not measured or reproduced (how often a race fires, whether more than
   one replica runs in production, what a caller outside the repos does) is marked as an inference in the reader's
   language ("inference:", "we infer that", or the `lang` equivalent).
6. **Keep the caveats a reviewer will ask about:** what the test does not cover, what stays out of scope, the cost of the
   fix, dependencies on other shown findings. If a test also fails at the base for a reason other than the problem
   (a fake with a different contract), say so plainly: it is the first thing a reviewer will find.
7. **Lengths:** `title` one short sentence; `what_happens` two to five sentences; `fix_summary` two to six sentences
   (for quality findings, the suggestion in plain words).
8. **Forbidden-terms check.** Before closing, search every rendered prose field of the shown findings for audit
   phrases, blame words and stray identifiers, and fix every hit. Extend the pattern with this run's pass names, the
   ids not shown, and the translation of each phrase into the run's `lang`:

```bash
python3 -c 'import glob, json, sys
for p in sorted(glob.glob(sys.argv[1] + "/findings/*.json")):
    f = json.load(open(p, encoding="utf-8"))
    if f.get("shown") is not True:
        continue
    texts = list((f.get("audience") or {}).values()) + [f.get("red_reason", "")]
    texts += [t.get("note", "") for t in f.get("tests") or []] + [e.get("note", "") for e in f.get("evidence") or []]
    for text in texts:
        print(f["id"], text)' <run-dir> \
  | rg -n -i 'candidate|red for the right reason|quality lens|contrast pass|baseline step|red-test-proof|races-distributed|owner-prose|verify-high|subagent|nobody|careless|obviously|badly done'
```

   Each output line is one field of one shown finding, so every hit is yours to fix. Empty output means the check
   passed.

## Evidence rules

- Every fact in the prose comes from the finding or its raw outputs. If it is not there, leave it out or ask.
- No commit SHAs other than the finding's own `sha_test`; no paths outside the cited ones unless they
  help the reader.
- Inferences labelled; measured facts stated plainly with their number.

## Output

One `ia.py finding set` per shown finding, in the run's `lang`. The three `audience` fields always; `red_reason`,
`tests` and `evidence` only when their prose needed rewriting. `tests` and `evidence` are lists, so pass the whole list
back with only the `note` texts changed and every other key copied exactly:

```bash
python3 <skill-dir>/ia.py finding set --run <run-dir> C-07 \
  'audience.title=<short sentence>' \
  'audience.what_happens=<two to five sentences: what the code does today, what happens, to whom; inferences labelled>' \
  'audience.fix_summary=<two to six sentences: what changes and why that way; caveats a reviewer will ask about>' \
  'red_reason=<same assertion and numbers, neutral wording>' \
  'evidence=[{"cite":"BACK/src/inventory/reserve.ts","from":88,"to":91,"note":"<rewritten note>"}]'
```

The hand-back is one line per finding (done, or the doubt you could not resolve) and the output of the forbidden-terms
check after your fixes.

## Done when

- Every shown finding has all three `audience` fields in the run's `lang`, and its `red_reason`, `tests[].note` and
  `evidence[].note` read as owner-facing prose in that language with every fact unchanged.
- The forbidden-terms check over those fields prints nothing.
- No prose blames anyone, uses audit jargon, gives an exploitation recipe, or states an inference as a fact.
