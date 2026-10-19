"""The two self-contained HTML reports: data from the run, code from git at the pinned base, look from a theme file."""
from __future__ import annotations

import html
import re
import string
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from . import cites as citesmod
from . import findings as findingsmod
from . import hygiene as hygienemod
from . import run as runmod
from .run import RunError, UsageError

ASSETS = Path(__file__).resolve().parent.parent / "assets"
DEFAULT_THEME = ASSETS / "theme.css"
TEMPLATE = ASSETS / "template.html"
SEVERITIES = ("high", "medium", "low")

LABELS: Dict[str, Dict[str, str]] = {
    "es": {
        "title_correctness": "Hallazgos de corrección en {system}",
        "title_quality": "Calidad y arquitectura de {system}",
        "intro_correctness": "Revisión de {repos} sobre la base fijada. Cada hallazgo trae el código afectado en esa "
                             "base y, cuando se pudo probar, un test que falla en esa base y una propuesta escrita de corrección.",
        "intro_quality": "Revisión de {repos} sobre la base fijada. Deja de lado los bugs: busca deficiencias de "
                         "calidad y de arquitectura, y para cada una dice dónde está, por qué importa y qué cambiar.",
        "brand_sub": "auditoría de sistema heredado",
        "toc": "Índice", "theme": "Cambiar tema", "footer": "Generado el {date} con ia.py render",
        "summary": "En una pantalla", "start_here": "Por dónde empezar", "strengths": "Lo que está bien",
        "how": "Cómo se hizo",
        "shown_of": "se muestran {shown} de {total}",
        "kpi_shown": "hallazgos en este informe", "kpi_high": "de severidad alta", "kpi_categories": "categorías",
        "filter_note": "Los demás quedaron afuera por el filtro del equipo dueño: sin confirmar, refutados por el "
                       "contraste o fuera de alcance.",
        "how_to_read": "Cómo leer este informe",
        "rubric": "<b>Severidad</b>, con un criterio fijo. <b>Alta:</b> expone datos o credenciales a quien no "
                  "debería, corrompe datos, o rompe una función entera. <b>Media:</b> produce un resultado incorrecto "
                  "que se nota, o expone información menor. <b>Baja:</b> robustez, observabilidad o una inconsistencia "
                  "visible sin pérdida.",
        "read_correctness": "<b>Test en rojo:</b> «falla en la base» dice cuántos casos del test fallan sobre la base "
                            "fijada; la rama del hallazgo trae solo ese test. Los links llevan a las líneas citadas en la "
                            "base fijada.",
        "read_quality": "<b>Esfuerzo:</b> S es un cambio chico y local, M toca varios archivos, L pide rediseñar una "
                        "parte. Los links llevan a las líneas citadas en la base fijada.",
        "start_lead": "Lo de mayor severidad y menor esfuerzo primero.",
        "col_id": "#", "col_finding": "Hallazgo", "col_category": "Categoría", "col_severity": "Severidad",
        "col_effort": "Esfuerzo", "col_file": "Archivo", "col_red": "Falla en la base", "col_green": "Verde",
        "col_note": "Nota", "col_alias": "Repo", "col_sha": "Base", "col_remote": "Remoto", "col_subdir": "Carpeta",
        "col_step": "Paso", "col_workers": "Quién lo hizo", "col_model": "Modelo de contraste",
        "col_family": "Familia", "col_verdict": "Veredicto",
        "what_happens": "Qué pasa", "evidence": "Evidencia en la base", "reproduction": "Reproducción",
        "tests": "Tests", "fix": "Propuesta", "suggestion": "Sugerencia", "measurement": "Medición",
        "category": "Categoría", "confidence": "Confianza", "branch": "Rama", "effort": "esfuerzo",
        "conf_execution": "probado al ejecutarlo", "conf_docs": "leído en el código y la documentación",
        "conf_unverified": "sin verificar",
        "sev_high": "alta", "sev_medium": "media", "sev_low": "baja",
        "same_family": "misma familia: {yes_no}", "yes": "sí", "no": "no",
        "cv_agree": "coincide", "cv_refute": "refuta", "cv_unsure": "no pudo decidir",
        "cv_refute_severity": "refuta la severidad", "cv_rebutted": "refutación respondida",
        "own_passes": "revisión propia", "author_model": "Modelo autor",
        "contrast_note": "Objeción del contraste", "rebuttal": "Refutación respondida",
        "no_remote": "sin remoto", "none": "ninguno",
        "how_base": "Se leyó cada repo en un commit fijo; todo lo citado sale de ese commit, no del árbol de trabajo.",
        "how_workers": "Quién revisó cada paso: las herramientas externas por nombre y, si no hubo, la revisión propia.",
        "how_contrast": "Un segundo modelo revisó cada hallazgo; si es de la misma familia que el autor, el contraste "
                        "vale menos y se dice.",
        "how_waivers": "Se cerró el paso con módulos sin revisar, y este fue el motivo:",
        "how_counts": "Lo que pasó el filtro:", "report_correctness": "Corrección", "report_quality": "Calidad",
        "in_history": "en el historial (commit {commit})",
        "no_file": "No se pudo leer {path} en {sha}.",
        "empty": "Ningún hallazgo pasó el filtro para este informe.",
    },
    "en": {
        "title_correctness": "Correctness findings in {system}",
        "title_quality": "Quality and architecture of {system}",
        "intro_correctness": "Review of {repos} at the pinned base. Each finding shows the affected code at that base "
                             "and, when it could be proven, a test that fails at that base and a written proposal for the fix.",
        "intro_quality": "Review of {repos} at the pinned base. It leaves bugs aside: it looks for quality and "
                         "architecture weaknesses, and for each one says where it is, why it matters and what to change.",
        "brand_sub": "inherited-system audit",
        "toc": "Contents", "theme": "Toggle theme", "footer": "Generated on {date} by ia.py render",
        "summary": "At a glance", "start_here": "Start here", "strengths": "What is good",
        "how": "How it was done",
        "shown_of": "showing {shown} of {total}",
        "kpi_shown": "findings in this report", "kpi_high": "of high severity", "kpi_categories": "categories",
        "filter_note": "The rest were left out by the owner-team filter: unconfirmed, refuted by the contrast or out "
                       "of scope.",
        "how_to_read": "How to read this report",
        "rubric": "<b>Severity</b>, with a fixed rubric. <b>High:</b> exposes data or credentials to the wrong people, "
                  "corrupts data, or breaks a whole feature. <b>Medium:</b> a visible wrong result, or minor "
                  "information exposure. <b>Low:</b> robustness, observability or a visible inconsistency without loss.",
        "read_correctness": "<b>Red test:</b> \"fails at the base\" says how many test cases fail on the pinned base; "
                            "the finding's branch carries only that test. Links point to the cited lines at the pinned "
                            "base.",
        "read_quality": "<b>Effort:</b> S is a small local change, M touches several files, L means redesigning a "
                        "part. Links point to the cited lines at the pinned base.",
        "start_lead": "Highest severity and lowest effort first.",
        "col_id": "#", "col_finding": "Finding", "col_category": "Category", "col_severity": "Severity",
        "col_effort": "Effort", "col_file": "File", "col_red": "Fails at the base", "col_green": "Green",
        "col_note": "Note", "col_alias": "Repo", "col_sha": "Base", "col_remote": "Remote", "col_subdir": "Folder",
        "col_step": "Step", "col_workers": "Done by", "col_model": "Contrast model",
        "col_family": "Family", "col_verdict": "Verdict",
        "what_happens": "What happens", "evidence": "Evidence at the base", "reproduction": "Reproduction",
        "tests": "Tests", "fix": "Proposal", "suggestion": "Suggestion", "measurement": "Measurement",
        "category": "Category", "confidence": "Confidence", "branch": "Branch", "effort": "effort",
        "conf_execution": "proven by running it", "conf_docs": "read in the code and docs",
        "conf_unverified": "unverified",
        "sev_high": "high", "sev_medium": "medium", "sev_low": "low",
        "same_family": "same family: {yes_no}", "yes": "yes", "no": "no",
        "cv_agree": "agrees", "cv_refute": "refutes", "cv_unsure": "could not decide",
        "cv_refute_severity": "refutes severity", "cv_rebutted": "rebutted",
        "own_passes": "own review", "author_model": "Author model",
        "contrast_note": "Contrast objection", "rebuttal": "Rebuttal to the contrast",
        "no_remote": "no remote", "none": "none",
        "how_base": "Each repo was read at a fixed commit; everything cited comes from that commit, not the worktree.",
        "how_workers": "Who reviewed each step: external tools by name and, when there were none, the own review.",
        "how_contrast": "A second model reviewed each finding; when it is from the same family as the author the "
                        "contrast is weaker, and that is stated.",
        "how_waivers": "A step was closed with modules not reviewed, and this is why:",
        "how_counts": "What passed the filter:", "report_correctness": "Correctness", "report_quality": "Quality",
        "in_history": "in history (commit {commit})",
        "no_file": "Could not read {path} at {sha}.",
        "empty": "No finding passed the filter for this report.",
    },
}


STEP_LABELS: Dict[str, Dict[str, str]] = {
    "es": {"baseline": "línea de base", "correctness": "corrección", "proof": "prueba con test rojo",
           "tests": "tests faltantes", "quality": "calidad", "contrast": "contraste",
           "verify": "verificación de lo grave", "filter": "filtro del equipo dueño", "prose": "redacción",
           "hygiene": "revisión previa a la entrega", "render": "armado del informe"},
    "en": {"baseline": "baseline", "correctness": "correctness", "proof": "red-test proof", "tests": "missing tests",
           "quality": "quality", "contrast": "contrast", "verify": "verification of the serious ones",
           "filter": "owner-team filter", "prose": "write-up", "hygiene": "pre-delivery checks",
           "render": "report build"},
}
PASS_LABELS: Dict[str, Dict[str, str]] = {
    "es": {"correctness-general": "revisión general de correctitud",
           "races-distributed": "revisión de carreras y sistemas distribuidos", "security": "revisión de seguridad",
           "quality-lenses": "revisión de calidad"},
    "en": {"correctness-general": "general correctness review",
           "races-distributed": "races and distributed-systems review", "security": "security review",
           "quality-lenses": "quality review"},
}
PASSES_DIR = ASSETS.parent / "references" / "passes"


def step_label(step: str, lang: Optional[str]) -> str:
    return STEP_LABELS.get(lang or "", STEP_LABELS["en"]).get(step, step)


def open_cell_label(cell: str, lang: Optional[str]) -> str:
    """`<module> / <pass>` as stored by coverage: the module stays, the pass becomes a localized label."""
    module, sep, pass_name = str(cell).partition(" / ")
    labels = PASS_LABELS.get(lang or "", PASS_LABELS["en"])
    fallback = "revisión" if lang == "es" else "review"
    return f"{module} / {labels.get(pass_name.strip(), fallback)}" if sep else module


def own_passes() -> set:
    """Names of the skill's own passes (`references/passes/*.md`): never printed, they are not workers."""
    try:
        return {p.stem for p in PASSES_DIR.glob("*.md")}
    except OSError:
        return set()


def labels_for(lang: Optional[str]) -> Dict[str, str]:
    return LABELS.get(lang or "", LABELS["en"])


def esc(value: object) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-") or "x"


def _anchor(fid: str) -> str:
    return "f-" + _slug(fid)


SENSITIVE_DIMENSIONS = ("security", "supply-chain")


def _safe(f: dict, text: object) -> str:
    """Free text of a finding; for security and supply-chain findings every line goes through hygiene masking."""
    text = "" if text is None else str(text)
    return hygienemod.mask_text(text) if f.get("dimension") in SENSITIVE_DIMENSIONS else text


def _prose(f: dict, key: str) -> str:
    audience = f.get("audience") if isinstance(f.get("audience"), dict) else {}
    return _safe(f, audience.get(key) or f.get(key) or "")


# --- git ------------------------------------------------------------------------------------------------------------

def snippet(repo: dict, path: str, start: int, end: int, context: int = 3) -> str:
    """The cited lines plus `context` lines around them, read at the repo's pinned sha, as an escaped <pre> block."""
    text = citesmod.blob_text(repo, path)
    if text is None:
        return ""
    lines = text.splitlines()
    # Mask the whole blob before slicing: a window that starts inside a private key still knows BEGIN is above it.
    keys = hygienemod.KeyMasker()
    masked = [keys.line(raw) for raw in lines]
    first, last = max(1, start - context), min(len(lines), end + context)
    rows = []
    for n in range(first, last + 1):
        cls = "ln hl" if start <= n <= end else "ln"
        rows.append(f'<span class="{cls}"><i>{n}</i>{esc(masked[n - 1])}</span>')
    return "<pre>" + "".join(rows) + "</pre>" if rows and start <= end <= len(lines) else ""


def _badge(severity: str, L: Dict[str, str]) -> str:
    sev = severity if severity in SEVERITIES else "na"
    text = L.get(f"sev_{severity}", severity or "-")
    return f'<span class="verdict {sev}">{esc(text)}</span>'


# secrets may sit in history: a cite there names the path and the commit, never the lines
HISTORY_NO_SNIPPET = ("security", "supply-chain")


def _cite_label(cite: str, start: int, end: int) -> str:
    return f"{cite}:{start}" if start == end else f"{cite}:{start}-{end}"


def _evidence(ev: dict, repos: Dict[str, dict], L: Dict[str, str], dimension: str = "") -> str:
    note = _safe({"dimension": dimension}, ev.get("note"))
    cite, start, end = ev.get("cite") or "", ev.get("from"), ev.get("to")
    label = _cite_label(cite, start, end)
    try:
        alias, path, commit = citesmod.parse_cite(cite)
    except ValueError:
        return f'<p class="aviso">{esc(label)}</p>'
    repo = repos.get(alias)
    if repo is None or not isinstance(start, int) or not isinstance(end, int):
        return f'<p class="aviso">{esc(label)}</p>'
    if commit:
        label = _cite_label(f"{alias}/{path}", start, end)
    url = citesmod.link_for(repo, path, start, end, commit)
    if url and not url.lower().startswith(("http://", "https://")):
        url = None
    head = f'<a class="cite" href="{esc(url)}"><code>{esc(label)}</code></a>' if url else f"<code>{esc(label)}</code>"
    if commit:
        head += f' · {esc(L["in_history"].format(commit=commit[:7]))}'
    if note:
        head += f" · {esc(note)}"
    if commit and dimension in HISTORY_NO_SNIPPET:
        return f'<figure class="code"><figcaption>{head}</figcaption></figure>'
    at = citesmod.at_commit(repo, commit)
    body = snippet(at, path, start, end)
    if not body:
        body = f'<p class="aviso">{esc(L["no_file"].format(path=cite, sha=at["sha"][:7]))}</p>'
    return f'<figure class="code"><figcaption>{head}</figcaption>{body}</figure>'


def _tests_table(f: dict, tests: List[dict], L: Dict[str, str]) -> str:
    green = any(t.get("green") for t in tests if isinstance(t, dict))  # legacy runs only: nothing writes it now
    rows = "".join(
        f'<tr><td><code>{esc(t.get("path"))}</code></td><td>{esc(t.get("red"))}</td>'
        + (f'<td>{esc(t.get("green"))}</td>' if green else "")
        + f'<td>{esc(_safe(f, t.get("note")))}</td></tr>' for t in tests if isinstance(t, dict))
    head = f'<th>{L["col_file"]}</th><th>{L["col_red"]}</th>' + (f'<th>{L["col_green"]}</th>' if green else "")
    return (f'<div class="tbl"><table class="tests"><thead><tr>{head}<th>{L["col_note"]}</th></tr></thead>'
            f'<tbody>{rows}</tbody></table></div>')


def _card_head(f: dict, L: Dict[str, str]) -> List[str]:
    return [f'<article class="issue" id="{_anchor(f["id"])}">',
            f'<header><span class="issue-n">{esc(f["id"])}</span><h3>{esc(_prose(f, "title"))}</h3>'
            f'{_badge(f.get("severity", ""), L)}</header>']


def _rebuttal(f: dict, L: Dict[str, str]) -> str:
    """For a rebutted refute: the contrast's objection (`note`) and the orchestrator's answer (`rebuttal`).

    Old runs wrote the answer over `note` and have no `rebuttal`: then `note` is the answer."""
    c = f.get("contrast") if isinstance(f.get("contrast"), dict) else {}
    if c.get("verdict") != "refute" or c.get("rebutted") is not True:
        return ""
    note, answer = str(c.get("note") or ""), str(c.get("rebuttal") or "")
    if not answer:
        note, answer = "", note
    out = ""
    if note:
        out += f'<p class="nota"><b>{esc(L["contrast_note"])}:</b> {esc(hygienemod.mask_text(note))}</p>'
    if answer:
        out += f'<p class="nota"><b>{esc(L["rebuttal"])}:</b> {esc(hygienemod.mask_text(answer))}</p>'
    return out


def _contrast_verdict(c: dict, L: Dict[str, str]) -> str:
    if c.get("verdict") == "refute" and c.get("rebutted") is True:
        return L["cv_rebutted"]
    if c.get("verdict") == "refute" and c.get("scope") == "severity":
        return L["cv_refute_severity"]
    return L.get("cv_" + str(c.get("verdict")), "-")


def correctness_card(f: dict, repos: Dict[str, dict], L: Dict[str, str]) -> str:
    parts = _card_head(f, L)
    meta = [f'<dt>{L["category"]}</dt><dd>{esc(f.get("category"))}</dd>',
            f'<dt>{L["confidence"]}</dt><dd>{esc(L.get("conf_" + str(f.get("confidence")), f.get("confidence")))}</dd>']
    if f.get("branch"):
        meta.append(f'<dt>{L["branch"]}</dt><dd><code>{esc(f["branch"])}</code></dd>')
    parts.append('<dl class="meta">' + "".join(meta) + "</dl>")
    parts.append(f'<h4>{L["what_happens"]}</h4><p>{esc(_prose(f, "what_happens"))}</p>')
    parts.append(_rebuttal(f, L))
    parts.append(f'<h4>{L["evidence"]}</h4>')
    parts.extend(_evidence(ev, repos, L, f.get("dimension") or "") for ev in f.get("evidence") or [] if isinstance(ev, dict))
    tests = [t for t in f.get("tests") or [] if isinstance(t, dict)]
    if f.get("red_reason") or tests:
        parts.append(f'<h4>{L["reproduction"]}</h4>')
        if f.get("red_reason"):
            parts.append(f"<p>{esc(_safe(f, f['red_reason']))}</p>")
        if tests:
            parts.append(_tests_table(f, tests, L))
    summary = _prose(f, "fix_summary")
    if summary:
        parts.append(f'<h4>{L["fix"]}</h4><p>{esc(summary)}</p>')
    parts.append("</article>")
    return "\n".join(parts)


def quality_card(f: dict, repos: Dict[str, dict], L: Dict[str, str]) -> str:
    parts = _card_head(f, L)
    effort = f" · {L['effort']} {esc(f['effort'])}" if f.get("effort") else ""
    parts.append(f'<p class="sev">{esc(f.get("category"))}{effort}</p>')
    m = f.get("measurement") if isinstance(f.get("measurement"), dict) else {}
    if m.get("tool") or m.get("value"):
        tool, value = (hygienemod.mask_text(str(m.get(k) or "")) for k in ("tool", "value"))
        parts.append(f'<p class="nota"><b>{L["measurement"]}:</b> <code>{esc(tool)}</code> {esc(value)}</p>')
    parts.append(f'<h4>{L["what_happens"]}</h4><p>{esc(_prose(f, "what_happens"))}</p>')
    parts.append(_rebuttal(f, L))
    parts.append(f'<h4>{L["evidence"]}</h4>')
    parts.extend(_evidence(ev, repos, L, f.get("dimension") or "") for ev in f.get("evidence") or [] if isinstance(ev, dict))
    if f.get("suggestion"):
        parts.append(f'<h4>{L["suggestion"]}</h4><p>{esc(f["suggestion"])}</p>')
    parts.append("</article>")
    return "\n".join(parts)


def ordered_categories(items: List[dict], order: Sequence[str]) -> List[str]:
    present = []
    for f in items:
        if f.get("category") not in present:
            present.append(f.get("category"))
    known = [c for c in order if c in present]
    return known + sorted(c for c in present if c not in known)


def _summary(report: str, items: List[dict], counts: Dict[str, int], cats: List[str], L: Dict[str, str]) -> str:
    def kpi(n: object, text: str) -> str:
        return f'<div class="card"><p class="kpi-n">{esc(n)}</p><p>{esc(text)}</p></div>'
    high = sum(1 for f in items if f.get("severity") == "high")
    has_counts = isinstance(counts, dict) and "shown" in counts and "total" in counts
    shown_of = L["shown_of"].format(shown=counts["shown"], total=counts["total"]) if has_counts else ""
    lead = f"{shown_of[:1].upper() + shown_of[1:]}. " if has_counts else ""
    parts = ['<div class="cards kpis">', kpi(len(items), L["kpi_shown"]), kpi(high, L["kpi_high"]),
             kpi(len(cats), L["kpi_categories"]), "</div>",
             f'<p class="lead">{esc(lead)}{esc(L["filter_note"])}</p>',
             f'<div class="callout info"><strong>{L["how_to_read"]}</strong><ul><li>{L["rubric"]}</li>'
             f'<li>{L["read_" + report]}</li></ul></div>']
    if not items:
        parts.append(f'<p class="aviso">{esc(L["empty"])}</p>')
        return "\n".join(parts)
    effort_col = f"<th>{L['col_effort']}</th>" if report == "quality" else ""
    rows = []
    for cat in cats:
        for f in (x for x in items if x.get("category") == cat):
            effort = f"<td>{esc(f.get('effort'))}</td>" if report == "quality" else ""
            rows.append(f'<tr><td>{esc(f["id"])}</td><td><a href="#{_anchor(f["id"])}">{esc(_prose(f, "title"))}</a></td>'
                        f'<td>{esc(cat)}</td><td>{_badge(f.get("severity", ""), L)}</td>{effort}</tr>')
    parts.append(f'<div class="tbl"><table><thead><tr><th>{L["col_id"]}</th><th>{L["col_finding"]}</th>'
                 f'<th>{L["col_category"]}</th><th>{L["col_severity"]}</th>{effort_col}</tr></thead>'
                 f'<tbody>{"".join(rows)}</tbody></table></div>')
    return "\n".join(parts)


def _start_here(ids: List[str], items: List[dict], L: Dict[str, str]) -> str:
    by_id = {f["id"]: f for f in items}
    rows = [f'<tr><td>{esc(i)}</td><td><a href="#{_anchor(i)}">{esc(_prose(by_id[i], "title"))}</a></td>'
            f'<td>{_badge(by_id[i].get("severity", ""), L)}</td><td>{esc(by_id[i].get("effort"))}</td></tr>'
            for i in ids if i in by_id]
    if not rows:
        return f'<p class="aviso">{esc(L["empty"])}</p>'
    return (f'<p class="lead">{esc(L["start_lead"])}</p><div class="tbl"><table><thead><tr><th>{L["col_id"]}</th>'
            f'<th>{L["col_finding"]}</th><th>{L["col_severity"]}</th><th>{L["col_effort"]}</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div>')


def _how(manifest: dict, report: str, everything: List[dict], L: Dict[str, str]) -> str:
    parts = [f"<p>{esc(L['how_base'])}</p>"]
    rows = []
    for r in manifest["repos"]:
        remote = f'<code>{esc(hygienemod.mask_line(r["remote"]))}</code>' if r.get("remote") else esc(L["no_remote"])
        rows.append(f'<tr><td>{esc(r["alias"])}</td><td><code title="{esc(r["sha"])}">{esc(r["sha"][:7])}</code></td>'
                    f'<td>{remote}</td><td>{esc(r.get("subdir") or "-")}</td></tr>')
    parts.append(f'<div class="tbl"><table><thead><tr><th>{L["col_alias"]}</th><th>{L["col_sha"]}</th>'
                 f'<th>{L["col_remote"]}</th><th>{L["col_subdir"]}</th></tr></thead><tbody>{"".join(rows)}</tbody>'
                 "</table></div>")
    lang = manifest.get("lang")
    own = own_passes()
    steps: Dict[str, List[str]] = {"correctness": [], "quality": [], "contrast": []}
    for f in everything:
        bucket = steps.get(f.get("report"))
        if bucket is not None and f.get("source") and f["source"] not in own and f["source"] not in bucket:
            bucket.append(f["source"])
        contrast = f.get("contrast") if isinstance(f.get("contrast"), dict) else {}
        if contrast.get("model") and contrast["model"] not in steps["contrast"]:
            steps["contrast"].append(contrast["model"])
    rows = [f'<tr><td>{esc(step_label(s, lang))}</td><td>'
            + (" ".join(f'<span class="who">{esc(w)}</span>' for w in sorted(ws)) or esc(L["own_passes"])) + "</td></tr>"
            for s, ws in steps.items()]
    parts.append(f"<p>{esc(L['how_workers'])}</p>")
    if manifest.get("author_model"):
        parts.append(f'<p>{esc(L["author_model"])}: <code>{esc(manifest["author_model"])}</code></p>')
    parts.append(f'<div class="tbl"><table><thead><tr><th>{L["col_step"]}</th><th>{L["col_workers"]}</th></tr></thead>'
                 f'<tbody>{"".join(rows)}</tbody></table></div>')
    contrasted = [f for f in everything if f.get("report") == report and f.get("shown") is True
                  and isinstance(f.get("contrast"), dict) and f["contrast"].get("model")]
    if contrasted:
        rows = []
        for f in contrasted:
            c = f["contrast"]
            fid = f'<a href="#{_anchor(f["id"])}">{esc(f["id"])}</a>'
            family = L["same_family"].format(yes_no=L["yes"] if c.get("same_family") else L["no"])
            verdict = _contrast_verdict(c, L)
            rows.append(f'<tr><td>{fid}</td><td><code>{esc(c["model"])}</code></td><td>{esc(family)}</td>'
                        f'<td>{esc(verdict)}</td></tr>')
        parts.append(f"<p>{esc(L['how_contrast'])}</p>")
        parts.append(f'<div class="tbl"><table><thead><tr><th>{L["col_id"]}</th><th>{L["col_model"]}</th>'
                     f'<th>{L["col_family"]}</th><th>{L["col_verdict"]}</th></tr></thead><tbody>{"".join(rows)}'
                     "</tbody></table></div>")
    waivers = [w for w in manifest.get("coverage_waivers") or [] if isinstance(w, dict)]
    if waivers:
        items = "".join(f'<li><strong>{esc(step_label(str(w.get("step")), lang))}'
                        f'</strong>: {esc(w.get("reason"))} <span class="ref">({esc("; ".join(open_cell_label(c, lang) for c in w.get("open") or []))})</span></li>'
                        for w in waivers)
        parts.append(f"<p>{esc(L['how_waivers'])}</p><ul>{items}</ul>")
    counts = manifest["filter"].get("counts") or {}
    items = "".join(f'<li>{esc(L["report_" + r])}: {esc(L["shown_of"].format(shown=c["shown"], total=c["total"]))}</li>'
                    for r, c in ((r, counts.get(r)) for r in findingsmod.REPORTS)
                    if isinstance(c, dict) and "shown" in c and "total" in c)
    if items:
        parts.append(f"<p>{esc(L['how_counts'])}</p><ul>{items}</ul>")
    parts.append(f"<p class=\"nota\">{esc(L['filter_note'])}</p>")
    return "\n".join(parts)


# --- assembly -------------------------------------------------------------------------------------------------------

def _require_filter(manifest: dict) -> dict:
    flt = manifest.get("filter")
    if not isinstance(flt, dict):
        raise RunError("the run has not been filtered; run `ia.py filter` first")
    return flt


def _read_theme(theme: Optional[Path]) -> str:
    path = Path(theme) if theme else DEFAULT_THEME
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise UsageError(f"cannot read theme {path}: {exc}")


def render_report(run: Path, report: str, theme: Optional[Path] = None) -> Path:
    run = Path(run)
    if report not in findingsmod.REPORTS:
        raise UsageError(f"unknown report {report!r}; expected one of {', '.join(findingsmod.REPORTS)}")
    manifest = runmod.load(run)
    flt = _require_filter(manifest)
    css = _read_theme(theme)
    L = labels_for(manifest.get("lang"))
    everything = findingsmod.load_all(run)
    items = [f for f in everything if f.get("report") == report and f.get("shown") is True]
    repos = {r["alias"]: r for r in manifest["repos"]}
    cats = ordered_categories(items, (manifest.get("sections") or {}).get(report) or [])
    counts = (flt.get("counts") or {}).get(report) or {}

    toc: List[str] = []
    used: set = set()
    body: List[str] = []

    def section(sid: str, heading: str, content: str, attrs: str = "") -> None:
        toc.append(f'    <li><a href="#{sid}">{esc(heading)}</a></li>')
        body.append(f'<section id="{sid}"{attrs}>\n<h2>{esc(heading)}</h2>\n{content}\n</section>')

    section("summary", L["summary"], _summary(report, items, counts, cats, L))
    if report == "quality":
        section("start-here", L["start_here"], _start_here(list(flt.get("start_here") or []), items, L))
    card = correctness_card if report == "correctness" else quality_card
    for cat in cats:
        cards = "\n".join(card(f, repos, L) for f in items if f.get("category") == cat)
        sid, n = "cat-" + _slug(cat), 1
        while sid in used:
            n += 1
            sid = f"cat-{_slug(cat)}-{n}"
        used.add(sid)
        section(sid, cat, cards, f' class="cat" data-category="{esc(cat)}"')
    strengths = manifest.get("strengths")
    if isinstance(strengths, list) and strengths:
        section("strengths", L["strengths"], "<ul>" + "".join(f"<li>{esc(s)}</li>" for s in strengths) + "</ul>")
    section("how", L["how"], _how(manifest, report, everything, L))

    system = manifest.get("system", "")
    repo_names = ", ".join(r["alias"] for r in manifest["repos"])
    page = string.Template(TEMPLATE.read_text(encoding="utf-8")).substitute(
        lang=esc(manifest.get("lang") if manifest.get("lang") in LABELS else "en"),
        title=esc(L["title_" + report].format(system=system)),
        style=css,
        toc_label=esc(L["toc"]),
        brand=esc(system),
        brand_sub=esc(L["brand_sub"]),
        toc="\n".join(toc),
        footer=esc(L["footer"].format(date=date.today().isoformat())),
        theme_label=esc(L["theme"]),
        intro=esc(L["intro_" + report].format(repos=repo_names)),
        body="\n".join(body),
    )
    out = run / f"{system}-{report}.html"
    out.write_text(page, encoding="utf-8")
    return out


def unfiltered_ids(run: Path) -> List[str]:
    """Ids of findings added after the last filter (their `shown` is still null)."""
    return [f["id"] for f in findingsmod.load_all(Path(run)) if f.get("shown") is None]


def render_run(run: Path, reports: Sequence[str], theme: Optional[Path] = None) -> List[Path]:
    """Writes every requested report; marks the `render` step done once all of them were written."""
    run = Path(run)
    _require_filter(runmod.load(run))
    _read_theme(theme)
    written = [render_report(run, r, theme) for r in reports]
    runmod.set_step(run, "render", "done")
    return written
