"""Write the workshop slides (workshop/episodes/pages/ia-slide-NN.html) from the data below.

Each slide is one self-contained page that the episode shows with a `page` step: the stage puts it in a browser
window of about 1472x774. Sequence diagrams are drawn here as SVG from a list of messages, so they share the slides'
colours: blue is ia.py (never calls a model), violet is a model, grey the person, teal git. Run it after editing:

    python3 workshop/slides/gen.py
"""
from __future__ import annotations

import html
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "episodes" / "pages"
DECK = "inherited-audit · Qué resuelve y cómo"

KIND = {  # actor kind -> (stroke, fill, text)
    "person": ("#6e6e73", "#f2f2f4", "#1d1d1f"),
    "model": ("#7a4fe0", "#f1ebfd", "#3d2385"),
    "cli": ("#2d6cdf", "#e8f0fd", "#163a7a"),
    "git": ("#2a8a76", "#e6f4f1", "#145246"),
    "files": ("#a0a0a0", "#fafafa", "#3a3a3c"),
}

CSS = """
*{box-sizing:border-box}
html,body{margin:0;height:100%;background:#fff;color:#1d1d1f;
  font-family:-apple-system,BlinkMacSystemFont,"SF Pro Text","Helvetica Neue",Helvetica,Arial,sans-serif}
.s{height:100%;display:flex;flex-direction:column;padding:34px 56px 22px}
.k{font-size:14px;letter-spacing:.12em;text-transform:uppercase;color:#7a4fe0;font-weight:600}
h1{margin:.25em 0 .1em;font-size:42px;line-height:1.1;letter-spacing:-.01em}
.lead{margin:0 0 18px;font-size:21px;color:#3a3a3c;max-width:1180px;line-height:1.4}
.body{flex:1;min-height:0;display:flex;flex-direction:column}
.foot{display:flex;justify-content:space-between;font-size:12.5px;color:#a0a0a0;padding-top:10px;
  border-top:1px solid #ececec;margin-top:12px}
code,.m{font-family:"SF Mono",Menlo,Monaco,monospace;font-size:.88em}
code{background:#f2f2f4;border-radius:5px;padding:.08em .35em}
ul{margin:0;padding-left:1.1em}li{margin:.35em 0}
.grid{display:grid;gap:18px}
.card{border-radius:14px;padding:20px 22px;background:#f7f7f9;border:1px solid #ececec}
.card h3{margin:0 0 8px;font-size:21px}
.card p,.card li{font-size:19px;line-height:1.45;color:#3a3a3c;margin:.3em 0}
.cli{background:#e8f0fd;border-color:#c9daf8}.cli h3{color:#163a7a}
.mod{background:#f1ebfd;border-color:#ddd0f8}.mod h3{color:#3d2385}
.no{background:#fff5f4;border-color:#f6d5d1}.no h3{color:#9a2a1f}
.big{font-size:27px;line-height:1.45}
.mid{justify-content:center}
.lg .card p{font-size:21.5px}.lg .card h3{font-size:24px}
.pill{display:inline-block;border-radius:999px;padding:.1em .7em;font-size:14px;font-weight:600}
.pc{background:#2d6cdf;color:#fff}.pm{background:#7a4fe0;color:#fff}
svg{width:100%;height:100%;display:block}
table{border-collapse:collapse;width:100%;font-size:16.5px}
td,th{padding:11px 12px;border-bottom:1px solid #ececec;text-align:left;vertical-align:top;line-height:1.4}
th{font-size:13px;letter-spacing:.08em;text-transform:uppercase;color:#7a7a7a}
"""


def esc(s: str) -> str:
    return html.escape(s, quote=True)


def inline(s: str) -> str:
    """`code` and **bold** inside slide text; everything else escaped."""
    out, code, bold = [], False, False
    i = 0
    while i < len(s):
        if s[i] == "`":
            out.append("</code>" if code else "<code>")
            code = not code
            i += 1
        elif s.startswith("**", i) and not code:
            out.append("</b>" if bold else "<b>")
            bold = not bold
            i += 2
        else:
            out.append(esc(s[i]))
            i += 1
    return "".join(out)


def page(n: int, total: int, title: str, lead: str, body: str, source: str) -> str:
    return (
        "<!doctype html><html lang=\"es\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        "<title>%s</title><style>%s</style></head><body><div class=\"s\">"
        "<div class=\"k\">%s</div><h1>%s</h1>%s<div class=\"body\">%s</div>"
        "<div class=\"foot\"><span>Fuente: %s</span><span>%d de %d</span></div>"
        "</div></body></html>\n"
        % (esc(title), CSS, esc(DECK), inline(title), ("<p class=\"lead\">%s</p>" % inline(lead)) if lead else "",
           body, inline(source), n, total)
    )


# ---- sequence diagrams ----

def seq(actors, msgs, width=1360, row=46, head=60):
    """actors: [(key, label, sublabel, kind)]. msgs: (from, to, text, kind) arrows; ("note", a, b, text) a band
    across lanes a..b; ("alt", a, b, text) a dashed band for an alternative path."""
    n = len(actors)
    lane = width / n
    x = {a[0]: lane * i + lane / 2 for i, a in enumerate(actors)}
    height = head + 22 + row * len(msgs) + 10
    out = ['<svg viewBox="0 0 %d %d" xmlns="http://www.w3.org/2000/svg" font-family="-apple-system,'
           'BlinkMacSystemFont,Helvetica,Arial,sans-serif">' % (width, height)]
    out.append('<defs>%s</defs>' % "".join(
        '<marker id="a-%s" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
        'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="%s"/></marker>' % (k, v[0])
        for k, v in KIND.items()))
    for key, label, sub, kind in actors:
        stroke, fill, text = KIND[kind]
        cx, w = x[key], min(lane - 18, 230)
        out.append('<line x1="%.1f" y1="%d" x2="%.1f" y2="%d" stroke="%s" stroke-width="1.5" '
                   'stroke-dasharray="4 5" opacity=".55"/>' % (cx, head, cx, height - 6, stroke))
        out.append('<rect x="%.1f" y="2" width="%.1f" height="%d" rx="10" fill="%s" stroke="%s" stroke-width="1.5"/>'
                   % (cx - w / 2, w, head - 6, fill, stroke))
        out.append('<text x="%.1f" y="%d" text-anchor="middle" font-size="17" font-weight="600" fill="%s">%s</text>'
                   % (cx, 26, text, esc(label)))
        out.append('<text x="%.1f" y="%d" text-anchor="middle" font-size="12.5" fill="%s" opacity=".8">%s</text>'
                   % (cx, 45, text, esc(sub)))
    y = head + 22
    num = 0
    for m in msgs:
        if m[0] in ("note", "alt"):
            a, b = sorted((x[m[1]], x[m[2]]))
            dash = ' stroke-dasharray="5 4"' if m[0] == "alt" else ""
            fill = "#fff8e6" if m[0] == "alt" else "#f7f7f9"
            stroke = "#d9a400" if m[0] == "alt" else "#d6d6da"
            out.append('<rect x="%.1f" y="%d" width="%.1f" height="%d" rx="7" fill="%s" stroke="%s"%s/>'
                       % (a - 80, y - 18, b - a + 160, row - 10, fill, stroke, dash))
            out.append('<text x="%.1f" y="%d" text-anchor="middle" font-size="15.5" fill="#3a3a3c">%s</text>'
                       % ((a + b) / 2, y + 4, label_svg(m[3])))
            y += row
            continue
        src, dst, text, kind = m
        stroke = KIND[kind][0]
        num += 1
        x1 = x[src]
        if src == dst:
            out.append('<path d="M%.1f %d h34 v16 h-32" fill="none" stroke="%s" stroke-width="2" '
                       'marker-end="url(#a-%s)"/>' % (x1 + 4, y - 8, stroke, kind))
            out.append('<text x="%.1f" y="%d" font-size="16" %s>%s</text>' % (x1 + 48, y + 5, HALO, label_svg(text)))
            bx = x1 - 18
        else:
            x2 = x[dst]
            d = 1 if x2 > x1 else -1
            out.append('<line x1="%.1f" y1="%d" x2="%.1f" y2="%d" stroke="%s" stroke-width="2" '
                       'marker-end="url(#a-%s)"/>' % (x1 + 6 * d, y, x2 - 6 * d, y, stroke, kind))
            out.append('<text x="%.1f" y="%d" text-anchor="%s" font-size="16" %s>%s</text>'
                       % (x1 + 16 * d, y - 8, "start" if d > 0 else "end", HALO, label_svg(text)))
            bx = x1 - 18 * d
        out.append('<circle cx="%.1f" cy="%d" r="10" fill="%s"/><text x="%.1f" y="%d" text-anchor="middle" '
                   'font-size="12" font-weight="700" fill="#fff">%d</text>' % (bx, y, stroke, bx, y + 4, num))
        y += row
    out.append("</svg>")
    return "".join(out)


HALO = 'fill="#1d1d1f" stroke="#fff" stroke-width="6" stroke-linejoin="round" paint-order="stroke"'


def label_svg(s: str) -> str:
    """`code` spans in a diagram label become monospace tspans."""
    parts = s.split("`")
    return "".join(('<tspan font-family="SF Mono,Menlo,monospace" font-size="14.5">%s</tspan>' % esc(p)) if i % 2
                   else esc(p) for i, p in enumerate(parts))


def legend(kinds) -> str:
    items = [(k, t) for k, t in (("cli", "ia.py: determinístico, nunca llama a un modelo"),
                                 ("model", "un modelo: no determinístico"), ("person", "la persona"), ("git", "git"))
             if k in kinds]
    return ('<div style="display:flex;gap:26px;font-size:15px;color:#3a3a3c;margin-bottom:10px">%s</div>' % "".join(
        '<span><span style="display:inline-block;width:22px;height:4px;border-radius:2px;background:%s;'
        'vertical-align:middle;margin-right:7px"></span>%s</span>' % (KIND[k][0], esc(t)) for k, t in items))


def diagram(actors, msgs) -> str:
    kinds = {a[3] for a in actors}
    return legend(kinds) + '<div style="flex:1;min-height:0">%s</div>' % seq(actors, msgs)


# ---- the slides ----

def s_problem():
    body = (
        '<div class="grid" style="grid-template-columns:1.25fr 1fr;align-items:center;flex:1">'
        '<div class="big"><ul>'
        '<li>Uno o varios repos: servicios, frontends, workers, CLIs o librerías, en TypeScript, Python, '
        'Java o Kotlin con Spring, Go u otro stack.</li>'
        '<li>Antes de construir encima tenés que saber <b>sobre qué estás parado</b>: bugs, carreras, fallas '
        'de sistemas distribuidos, tests que faltan, deuda de diseño.</li>'
        '<li>Una revisión a ojo da opiniones. El equipo dueño necesita <b>pruebas</b> y un reporte corto que '
        'pueda leer sin sentirse acusado.</li></ul></div>'
        '<div class="grid" style="align-content:start">'
        '<div class="card cli"><h3>Le decís al agente</h3><p><i>«Auditá mi-servicio antes de que empecemos»</i></p></div>'
        '<div class="card"><h3>No es para</h3><p>Revisar un diff o un PR: para eso está <code>/review-bugbot</code>. '
        'Tampoco audita UI o accesibilidad, ni arregla lo que encuentra.</p></div></div></div>')
    return ("Heredaste un sistema que no construiste", "", body, "`skill/SKILL.md` («When to use»), `docs/showcase.md`")


def s_delivers():
    body = (
        '<div class="lg" style="flex:1;display:flex;flex-direction:column;justify-content:center">'
        '<div class="grid" style="grid-template-columns:repeat(3,1fr)">'
        '<div class="card"><h3>Reporte de correctitud</h3><p>Bugs, carreras, sistemas distribuidos, seguridad, '
        'cadena de suministro y contenedor. <b>Cada hallazgo de código, probado por un test que falla</b> en el '
        'commit fijado.</p></div>'
        '<div class="card"><h3>Reporte de calidad y arquitectura</h3><p>Código, diseño, arquitectura, resiliencia y '
        'documentación. Cada hallazgo con <b>sugerencia, esfuerzo</b> y, si es un número, la medición.</p></div>'
        '<div class="card"><h3>Ramas locales</h3><p>Una por hallazgo confirmado, con <b>un commit de solo tests en '
        'rojo</b> y la propuesta de arreglo escrita. Más una rama con los tests unitarios y e2e que faltaban, '
        'verdes en la base.</p></div></div>'
        '<div class="card no" style="margin-top:18px"><h3>Nunca</h3><p>hace push, abre PRs '
        'o issues · cambia código de producción · instala algo sin preguntar · deja los reportes donde git los '
        'pueda commitear (llevan hallazgos de seguridad)</p></div></div>')
    return ("Qué entrega, y qué no hace nunca", "Dos HTML autocontenidos para el equipo dueño y las pruebas en git.",
            body, "`docs/showcase.md` («Lo que lo distingue»), `skill/SKILL.md` («Ground rules»)")


STEPS = [  # (step, Cursor worker, who closes it: "cli" or "model")
    ("baseline", "pasada propia (inventario) + `ia.py detect` y `baseline`", "both"),
    ("correctness", "`/review-bugbot` · carreras y seguridad: pasadas propias · semgrep, gitleaks, trivy, osv-scanner",
     "model"),
    ("proof", "pasada propia: un subagente por candidato, en su worktree", "model"),
    ("tests", "obra/superpowers · Playwright · pasada e2e-infra", "model"),
    ("quality", "cuatro lentes + wshobson/agents · dependency-cruiser, knip, jscpd", "model"),
    ("contrast", "`agent -p --mode ask` con un modelo de otra familia", "model"),
    ("verify", "subagente nuevo, que no vio el razonamiento", "model"),
    ("filter", "`ia.py filter`", "cli"),
    ("prose", "pasada propia, sin jerga ni culpas", "model"),
    ("hygiene", "`ia.py hygiene`", "cli"),
    ("render", "`ia.py render`", "cli"),
]


PILLS = {"cli": '<span class="pill pc">ia.py</span>', "model": '<span class="pill pm">un modelo</span>',
         "both": '<span class="pill pm">un modelo</span> <span class="pill pc">ia.py</span>'}


def s_steps():
    rows = "".join(
        '<tr><td class="m" style="width:150px"><b>%s</b></td><td>%s</td><td style="width:220px">'
        '%s</td></tr>' % (esc(s), inline(w), PILLS[k]) for s, w, k in STEPS)
    body = ('<table><tr><th>Paso</th><th>Worker en Cursor</th><th>Lo hace</th></tr>%s</table>' % rows)
    return ("Dirige la obra; los workers la construyen",
            "La skill tiene el checklist, el orden y los criterios de aceptación. Regla: un worker externo donde "
            "exista y sea bueno, una pasada propia donde no haya nada.",
            body, "`docs/referencia.md` («El checklist»), `skill/references/workers.md` (Cursor)")


def s_split():
    body = (
        '<div class="grid" style="grid-template-columns:1fr 210px 1fr;align-items:stretch;flex:1">'
        '<div class="card cli"><h3>Determinístico · <code>ia.py</code></h3><p>Python, solo biblioteca estándar. '
        '<b>Nunca llama a un modelo.</b> Misma entrada, misma salida.</p><ul>'
        '<li><code>init</code> fija el commit; rechaza un repo con cambios o una salida commiteable</li>'
        '<li><code>detect</code> · <code>baseline</code>: stack, workers que faltan, suite medida</li>'
        '<li><code>finding add|set</code>: valida el esquema; rechaza un confirmado sin test rojo</li>'
        '<li><code>coverage</code> · <code>step</code>: no cierra un paso con módulos sin visitar</li>'
        '<li><code>merge-check</code> · <code>cite-check</code> · <code>hygiene</code></li>'
        '<li><code>filter</code> · <code>render</code> · <code>publish</code> (escribe, nunca corre)</li></ul></div>'
        '<div style="display:flex;flex-direction:column;justify-content:center;text-align:center;gap:14px">'
        '<div style="font-size:15px;color:#7a7a7a;letter-spacing:.08em;text-transform:uppercase">la regla</div>'
        '<div style="font-size:25px;line-height:1.3;font-weight:700"><span style="color:#7a4fe0">El modelo '
        'propone</span><br>↓<br><span style="color:#2d6cdf">el CLI decide si entra</span></div>'
        '<div style="font-size:14.5px;color:#3a3a3c">Cada paso se cierra con un comando que puede negarse '
        '(sale con 1 y dice por qué).</div></div>'
        '<div class="card mod"><h3>No determinístico · un modelo</h3><p>Juicio: dos corridas no encuentran '
        'exactamente lo mismo. Por eso cada resultado pasa por una compuerta.</p><ul>'
        '<li>inventario del sistema y elección de módulos</li>'
        '<li>pasadas de correctitud, carreras y seguridad</li>'
        '<li>escribir el test que falla, y los tests que faltaban</li>'
        '<li>las cuatro lentes de calidad</li>'
        '<li>contraste con otro modelo, y verificación de cada severidad alta</li>'
        '<li>la prosa para el equipo dueño</li></ul></div></div>')
    return ("Qué es determinístico y qué no", "", body,
            "`docs/referencia.md` («Se cierra cuando»), `skill/SKILL.md` («The CLI and where it lives»)")


def s_seq_run():
    actors = [("p", "Persona", "", "person"), ("a", "Agente", "Cursor · GPT-5.6 Terra", "model"),
              ("w", "Workers", "subagentes y /review-bugbot", "model"), ("c", "ia.py", "CLI determinístico", "cli"),
              ("g", "Repos", "git", "git"), ("r", "Corrida", "manifest y hallazgos", "files")]
    msgs = [
        ("p", "a", "«Auditá mi-servicio»", "person"),
        ("a", "c", "`init`", "model"),
        ("c", "g", "fija el commit; rechaza repos con cambios", "cli"),
        ("c", "r", "`manifest.json`, fuera de los repos", "cli"),
        ("a", "c", "`detect` · `baseline`", "model"),
        ("a", "p", "faltan estos workers: ¿instalo alguno? (una sola vez)", "model"),
        ("a", "w", "una pasada por módulo: ruta de la pasada, corrida, modelo", "model"),
        ("w", "c", "`finding add`: candidatos con citas al commit fijado", "model"),
        ("note", "a", "g", "proof · contrast · verify (las dos diapositivas que siguen)"),
        ("a", "c", "`filter` · `hygiene` · `cite-check` · `render`", "model"),
        ("c", "r", "dos HTML: correctitud y calidad", "cli"),
        ("a", "p", "«se muestran N de M» · ramas locales, sin push", "model"),
    ]
    return ("La corrida, de punta a punta", "", diagram(actors, msgs),
            "`skill/SKILL.md` («The checklist»), `docs/showcase.md` (casos 1 y 4)")


def s_seq_proof():
    actors = [("a", "Agente", "orquesta", "model"), ("s", "Subagente", "en su propio worktree", "model"),
              ("g", "Repo", "rama fix/c-01", "git"), ("c", "ia.py", "CLI determinístico", "cli"),
              ("r", "Corrida", "outputs/", "files")]
    msgs = [
        ("a", "g", "`worktree add` en el commit fijado", "model"),
        ("a", "s", "candidato C-01 + su worktree", "model"),
        ("s", "g", "un commit de solo tests", "model"),
        ("s", "s", "corre el test: falla por una aserción", "model"),
        ("s", "r", "`outputs/C-01-red.txt`", "model"),
        ("s", "c", "`finding set` verdict=confirmed, tests, red_reason", "model"),
        ("alt", "s", "c", "sin tests ni red_reason: ia.py lo rechaza (sale con 1)"),
        ("alt", "a", "g", "no da rojo con una aserción, o el arreglo pide un refactor: se descarta con el motivo"),
        ("a", "g", "`worktree remove`", "model"),
        ("a", "c", "`merge-check`: las ramas combinan de a pares", "model"),
    ]
    return ("Probar un hallazgo: rojo por la razón correcta",
            "Un import roto o un error de setup no cuentan. El arreglo queda escrito; la skill nunca lo aplica.",
            diagram(actors, msgs), "`docs/showcase.md` (caso 2), `skill/SKILL.md` («Step 1: proof»)")


def s_seq_contrast():
    actors = [("a", "Agente", "GPT-5.6 Terra · autor", "model"),
              ("x", "agent -p --mode ask", "Sonnet 5.5 High · solo lectura", "model"),
              ("v", "Subagente nuevo", "no vio el razonamiento", "model"), ("c", "ia.py", "CLI determinístico", "cli")]
    msgs = [
        ("a", "c", "`set author_model=GPT-5.6 Terra`", "model"),
        ("a", "x", "pasada de contraste + la corrida", "model"),
        ("x", "a", "por hallazgo: agree · refute · unsure", "model"),
        ("a", "c", "`finding set` contrast.model, same_family=false, verdict", "model"),
        ("alt", "a", "c", "refute de severidad: se baja · refute del hallazgo: se descarta o se rebate con una cita"),
        ("a", "v", "cada severidad alta: solo el hallazgo, la rama y la corrida", "model"),
        ("v", "c", "`finding set`: se sostiene, baja o se descarta", "model"),
        ("a", "c", "`filter`", "model"),
        ("c", "a", "«se muestran N de M»: nada `unverified` entra", "cli"),
    ]
    return ("Contraste y verificación: otros ojos antes del filtro",
            "Un modelo de otra familia revisa en solo lectura; uno nuevo verifica lo grave sin heredar sesgos.",
            diagram(actors, msgs), "`skill/SKILL.md` («contrast», «verify»), `docs/showcase.md` (caso 3)")


def s_protects():
    rows = [
        ("Nunca hace push, ni PRs, ni issues; `publish` solo deja los comandos escritos",
         "Las ramas y los reportes quedan en tu máquina: dónde los compartís lo decidís vos"),
        ("`init` y `hygiene` se niegan a dejar la corrida donde git la pueda commitear",
         "Si copiás un reporte a mano adentro de un repo, nada lo impide"),
        ("`cite-check` confirma que cada cita existe en el commit fijado",
         "Que la cita exista no prueba el hallazgo: eso lo hacen el test rojo, el contraste y la verificación"),
        ("`hygiene` busca secretos e ids de 40 caracteres en ramas y salidas",
         "Es una búsqueda por patrones: un secreto con un formato desconocido puede pasar"),
        ("Lo `unverified` no entra en los reportes",
         "El filtro aplica una regla; no juzga si un hallazgo confirmado le importa a tu equipo"),
    ]
    body = ('<div style="flex:1;display:flex;flex-direction:column;justify-content:center">'
            '<table style="font-size:20.5px"><tr><th>Te protege</th><th>No te protege</th></tr>%s</table></div>'
            ) % "".join(
        "<tr><td>%s</td><td>%s</td></tr>" % (inline(a), inline(b)) for a, b in rows)
    return ("Qué te protege y qué no", "", body, "`docs/showcase.md` («Qué te protege y qué no»)")


# ---- what a pass costs (measured, tokens.json) ----

SWEET = (1300, 6300)  # lines: tokens per line already flat and every run read the whole module


def xy_panel(runs, x0, w, h, title, yof, ymax, yticks, yfmt):
    """One log-x panel: a dot per run, a line through the mean per size, the sweet-spot band."""
    import math
    lo, hi = math.log10(150), math.log10(20000)
    px = lambda v: x0 + 64 + (math.log10(v) - lo) / (hi - lo) * (w - 84)
    py = lambda v: 40 + (1 - v / ymax) * (h - 90)
    o = ['<text x="%.1f" y="22" font-size="17" font-weight="600" fill="#1d1d1f">%s</text>' % (x0 + 64, esc(title))]
    o.append('<rect x="%.1f" y="40" width="%.1f" height="%d" fill="#2a8a76" opacity=".10"/>'
             % (px(SWEET[0]), px(SWEET[1]) - px(SWEET[0]), h - 90))
    o.append('<text x="%.1f" y="56" text-anchor="middle" font-size="13" font-weight="600" fill="#145246">'
             'sweet spot</text>' % ((px(SWEET[0]) + px(SWEET[1])) / 2))
    for t in yticks:
        o.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="#ececec"/>' % (x0 + 64, py(t), x0 + w - 20, py(t)))
        o.append('<text x="%.1f" y="%.1f" text-anchor="end" font-size="12.5" fill="#7a7a7a">%s</text>'
                 % (x0 + 56, py(t) + 4, yfmt(t)))
    for t in (200, 500, 1000, 2000, 5000, 10000):
        o.append('<text x="%.1f" y="%d" text-anchor="middle" font-size="12.5" fill="#7a7a7a">%s</text>'
                 % (px(t), h - 30, "{:,}".format(t).replace(",", ".")))
    o.append('<text x="%.1f" y="%d" text-anchor="middle" font-size="13" fill="#3a3a3c">líneas del módulo '
             '(escala logarítmica)</text>' % (x0 + 64 + (w - 84) / 2, h - 8))
    sizes = sorted({r["lines"] for r in runs})
    means = [(L, sum(yof(r) for r in runs if r["lines"] == L) / len([r for r in runs if r["lines"] == L]))
             for L in sizes]
    o.append('<polyline fill="none" stroke="#7a4fe0" stroke-width="2.5" points="%s"/>'
             % " ".join("%.1f,%.1f" % (px(L), py(m)) for L, m in means))
    for r in runs:
        full = r["module_files_read"] >= r["files"]
        o.append('<circle cx="%.1f" cy="%.1f" r="6" fill="%s" stroke="#7a4fe0" stroke-width="2"/>'
                 % (px(r["lines"]), py(yof(r)), "#7a4fe0" if full else "#fff"))
    return "".join(o), px, py


def s_tokens():
    data = json.loads((Path(__file__).resolve().parent / "tokens.json").read_text(encoding="utf-8"))
    runs = data["runs"]
    w, h = 660, 400
    a, pxa, pya = xy_panel(runs, 0, w, h, "Tokens por pasada (miles)", lambda r: r["tokens"] / 1000, 1000,
                           (0, 250, 500, 750, 1000), lambda t: "%dk" % t)
    b, pxb, pyb = xy_panel(runs, w + 40, w, h, "Tokens por línea del módulo", lambda r: r["tokens"] / r["lines"], 750,
                           (0, 250, 500, 750), lambda t: "%d" % t)
    partial = [r for r in runs if r["module_files_read"] < r["files"]]
    note = ""
    if partial:
        r = partial[0]
        note = ('<text x="%.1f" y="%.1f" text-anchor="end" font-size="13" %s>leyó %d de %d archivos</text>'
                % (pxa(r["lines"]) - 10, pya(r["tokens"] / 1000) + 4, HALO, r["module_files_read"], r["files"]))
    svg = ('<svg viewBox="0 0 %d %d" xmlns="http://www.w3.org/2000/svg" font-family="-apple-system,'
           'BlinkMacSystemFont,Helvetica,Arial,sans-serif">%s%s%s</svg>' % (2 * w + 40, h, a, b, note))
    lo = [r["tokens"] for r in runs if r["lines"] < 1000]
    per_call = fit([r["tool_calls"] for r in runs], [r["tokens"] for r in runs])
    sweet = [r["tokens"] / r["lines"] for r in runs if SWEET[0] <= r["lines"] <= SWEET[1]]
    k = lambda v: "{:,}".format(int(round(v, -3)) // 1000).replace(",", ".") + "k"
    cards = (
        '<div class="grid" style="grid-template-columns:repeat(3,1fr);gap:14px;margin-top:10px">'
        '<div class="card"><h3>Hay un piso</h3><p>Con menos de 1.000 líneas, igual cuesta %s a %s: la skill se lee '
        'siempre y cada vuelta reenvía el contexto.</p></div>'
        '<div class="card"><h3>Pesan las vueltas</h3><p>Cada llamada a una herramienta suma ~%s tokens '
        '(R² %s). Muchos archivos chicos cuestan más que pocos grandes.</p></div>'
        '<div class="card" style="background:#e6f4f1;border-color:#bfe3da"><h3 style="color:#145246">'
        '1.300 a 6.200 líneas por subagente</h3><p>%d a %d tokens por línea y el módulo leído entero. Con 12.357, '
        'una de dos corridas dejó archivos sin leer.</p></div></div>'
        % (k(min(lo)), k(max(lo)), "{:,}".format(int(round(per_call[1], -2))).replace(",", "."), ("%.2f" % per_call[2]).replace(".", ","),
           min(sweet), max(sweet)))
    body = ('<div style="flex:1;min-height:0">%s</div>%s' % (svg, cards))
    source = ("medido el %s con `%s` en `cursor-agent`, pasada `%s` en solo lectura, 2 corridas por tamaño "
              "(`workshop/slides/tokens.json`)" % (data["measured"], data["model"], data["pass"]))
    share = [r["cache_read"] / r["tokens"] for r in runs]
    return ("Cuántos tokens procesa una pasada, según el tamaño del módulo",
            "Entrada más salida de una pasada de correctitud. Entre el %d %% y el %d %% es lectura de caché, que se "
            "cobra más barata. El círculo vacío es una corrida que no leyó todo el módulo."
            % (round(100 * min(share)), round(100 * max(share))), body, source)


def fit(xs, ys):
    """Least squares y = a + b*x: (a, b, r2)."""
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sum((x - mx) ** 2 for x in xs)
    a = my - b * mx
    ss = sum((y - a - b * x) ** 2 for x, y in zip(xs, ys))
    return a, b, 1 - ss / sum((y - my) ** 2 for y in ys)


SLIDES = [s_problem, s_delivers, s_steps, s_split, s_seq_run, s_seq_proof, s_seq_contrast, s_tokens, s_protects]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("ia-slide-*.html"):
        old.unlink()
    for i, fn in enumerate(SLIDES, 1):
        title, lead, body, source = fn()
        (OUT / ("ia-slide-%02d.html" % i)).write_text(page(i, len(SLIDES), title, lead, body, source),
                                                       encoding="utf-8")
        print("episodes/pages/ia-slide-%02d.html  %s" % (i, title))


if __name__ == "__main__":
    main()
