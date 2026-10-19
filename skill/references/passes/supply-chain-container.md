# Pass: supply-chain-container (step 1)

You check what the system is built from and what it ships in: dependencies, lockfiles, CI references, container
images. Most of these findings cannot be proven with a code test, so they live or die by
`references/verification-rules.md`: until you have run or looked it up, it is a guess.

`<skill-dir>` is two folders above this file (the folder that holds `SKILL.md` and `ia.py`).

## Scope

- **Supply chain:** lockfiles present, committed and in sync with the manifest; installs that ignore the lockfile
  (`npm install` instead of `npm ci`, `pip install` without hashes or constraints); dependency ranges whose lowest
  allowed version breaks the build or the suite; mutable references (a CI action pinned to a tag or branch instead of a
  SHA, `latest` image tags, git dependencies on a branch); an action SHA whose comment names another version; known
  vulnerabilities in resolved versions (osv-scanner, trivy); an SBOM if the team claims one.
- **Container hardening:** base image pinned by digest or at least a specific tag; runs as a non-root user; no build
  tools, package managers or shells left in the final stage when the image claims to be minimal; secrets passed as
  build args or copied into layers; `.dockerignore` keeps `.env`, `.git` and local files out; health check present;
  writable filesystem only where needed.
- **Secrets in history:** gitleaks over the repo, read as leads, never quoted.
- Interpreting the output of the static scanners the person installed (semgrep, gitleaks, trivy, osv-scanner).

## Out of scope

- Application security in code (`security.md`), resilience settings like probes and timeouts (the quality lenses).
- Upgrading anything, editing manifests or images, making commits. This pass is read-only. Installing a scanner is never
  done here; use what `ia.py detect` recorded in `tools`.
- Contacting registries with credentials or pushing anything. Unauthenticated read-only lookups (a registry page, a
  release API) are expected.

## Inputs

- The run dir and your scope.
- `manifest.json`: `repos[]` (`alias`, `path`, `subdir`, `sha`), `lang`, `tools` (which scanners are on the PATH),
  `baseline.<ALIAS>.plan` (`deps`, `install_cmd`), `sections.correctness`.
- `python3 <skill-dir>/ia.py finding list --run <run-dir> --report correctness` to avoid duplicates.

## Method

1. Work in a throwaway worktree at the pinned SHA that the orchestrator gives you, or read with
   `git -C <path> show <sha>:<file>`. Never scan the live checkout.
2. Run the installed scanners against that worktree and save their raw output under the run dir's `outputs/` (for
   example `outputs/osv-BACK.txt`), with any secret value masked before saving. Read the output; do not paste it into
   findings wholesale.
3. Lockfiles: compare manifest and lockfile; check what CI and the Dockerfile actually run to install.
4. Ranges: for each direct dependency with a range, find its lowest allowed version. If the orchestrator allows it,
   resolve and install at the floor in the throwaway worktree and run the suite (rule 2). Otherwise label the finding
   `docs` or `unverified` accordingly.
5. CI references: list every `uses:` and image reference; look up each SHA and tag against its source (`gh api` GET
   or the registry) and check that the SHA belongs to the tag in the comment (rule 7). Confirm who you are
   authenticated as before concluding something is missing (rule 6).
6. Images: read every Dockerfile stage. Where Docker is available and the person agreed, build the image and check the
   claims by running it (`id -u`, whether a shell exists); otherwise stop at `docs`.
7. For each candidate, say which failure it allows (rule 4: name the exact failure a control stops, not the control).

## Evidence rules

- Cite the manifest, lockfile, workflow or Dockerfile lines at the pinned SHA (`ALIAS/path`, `from`/`to`, relative to
  the alias root).
- Choose `confidence` honestly: `execution` when you ran it (scanner, floor install, image build, lookup that shows the
  mismatch); `docs` when you checked it against the authoritative source without running; `unverified` otherwise.
  `unverified` findings stay out of the reports and are told to the person.
- External references (SHAs, tags, digests, versions) are looked up, never written from memory.
- A scanner hit is a lead. Confirm the vulnerable code path or version is actually present before filing it, and name
  the advisory id.
- Never quote a secret. Name the file and line, mask the value.

## Output

These findings skip the proof pass: you confirm them here. One `ia.py finding add` per finding, JSON on stdin, prose
fields in the run's `lang`, with the verdict chosen by what you actually did:

- **Verified by execution** (a scanner, a floor install, an image build or a lookup ran and its output is saved under
  `outputs/`): `verdict: confirmed`, `confidence: execution`, the command in `measurement.tool`, and the saved file in
  `outputs.suite` (or named in an `evidence[].note`). `ia.py` refuses it without both.
- **Verified by documentation** (checked against the authoritative source, not run): `verdict: confirmed`,
  `confidence: docs`.
- **Neither**: `verdict: candidate`, `confidence: unverified`. It stays out of the reports and is told to the person.

```bash
python3 <skill-dir>/ia.py finding add --run <run-dir> - <<'EOF'
{"report": "correctness", "category": "<a category from sections.correctness>", "dimension": "supply-chain",
 "title": "<one technical line>", "verdict": "confirmed", "severity": "medium", "confidence": "execution",
 "source": "supply-chain-container",
 "what_happens": "<which failure this allows and when; what you ran or looked up and what it showed>",
 "evidence": [{"cite": "BACK/package-lock.json", "from": 410, "to": 418, "note": "resolved version with a known advisory, see outputs/osv-BACK.txt"}],
 "measurement": {"tool": "osv-scanner --lockfile package-lock.json", "value": "1 advisory (<advisory id>)"},
 "outputs": {"red": "", "green": "", "suite": "outputs/osv-BACK.txt"},
 "fix_summary": "<upgrade to the first fixed version, for example>"}
EOF
```

Use `dimension: "container"` for image findings. CI and build-only findings will later get `exclude: "tooling"` in the
filter; still file them, the filter decides. If you cannot run commands that write (a read-only host mode), print each
finding as a fenced `json` block instead and the orchestrator adds them.

## Done when

- Every installed scanner ran on the pinned SHA and its masked raw output is under `outputs/`.
- Every lockfile, install command, CI reference and Dockerfile stage of the scope was checked.
- Every finding names the failure it allows, cites the base and carries an honest confidence: `confirmed` with its
  command and saved output (`execution`) or its source (`docs`), otherwise `candidate` and `unverified`.
