# Referencia

Para consultar: el checklist, las opciones, la carpeta de una corrida, los campos de un hallazgo y los códigos de
salida. La fuente de verdad es lo que lee el agente, en inglés: [`skill/SKILL.md`](../skill/SKILL.md) y
[`skill/references/`](../skill/references/). Esto es un resumen para personas.

## El checklist

Once pasos, en este orden; cada uno queda en `manifest.json` como `pending`, `in_progress`, `done` o `skipped`, y
`ia.py status` dice cuál sigue.

| Paso | Qué produce | Se cierra cuando |
|---|---|---|
| `baseline` | Commit fijado, inventario del sistema, suite medida, obreros disponibles | `ia.py baseline` tiene resultado para cada repo; un repo sin comando de tests queda abierto hasta que registrás el resultado a mano con `ia.py set` (`baseline.<ALIAS>.result.passed`, `failed`, `total`…; `total=0` si no tiene runner) |
| `correctness` | Candidatos de bugs, races, sistemas distribuidos, seguridad, cadena de suministro y contenedor, con citas en la base | El agente lo marca hecho |
| `proof` | Una rama local por candidato con un commit de solo tests, rojo por una aserción; o descartado con motivo | Todas las ramas combinan de a pares (`merge-check`) |
| `tests` | Tests unitarios y e2e que faltaban, verdes en la base, en una rama aparte por repo | Esa rama combina con las de los hallazgos |
| `quality` | Hallazgos de calidad y arquitectura, cada uno con sugerencia, esfuerzo y, si es un número, la medición | El agente lo marca hecho |
| `contrast` | Veredicto de otro modelo (`agree`, `refute`, `unsure`) sobre cada hallazgo | Lo refutado se rebatió con evidencia o se descartó |
| `verify` | Cada severidad alta re-verificada por un subagente nuevo | El agente lo marca hecho |
| `filter` | Qué ve el equipo dueño y los conteos «N de M» | `ia.py filter` |
| `prose` | Título, qué pasa y arreglo en el idioma del reporte, sin jerga ni culpas | El agente lo marca hecho, después del control de términos prohibidos |
| `hygiene` | Ramas y salidas sin secretos ni archivos locales, corrida no commiteable | `ia.py hygiene` da limpio |
| `render` | Los dos HTML | `ia.py render` |

## Obreros por host

Regla: un obrero externo donde exista y sea bueno; una pasada propia de la skill donde no haya nada. Algunos ejemplos;
la tabla completa, con los comandos de instalación, está en
[`skill/references/workers.md`](../skill/references/workers.md).

| Paso | Claude Code | Cursor |
|---|---|---|
| Bugs generales | `/code-review` por módulo | `/review-bugbot` |
| Seguridad del repo entero | `claude-security` | pasada propia |
| Races y sistemas distribuidos | pasada propia | pasada propia |
| Análisis estático | semgrep, gitleaks, trivy, osv-scanner, si están | ídem |
| Contraste | `/codex:adversarial-review` | `agent` con otro modelo, en modo de solo lectura |

Las pasadas propias están en [`skill/references/passes/`](../skill/references/passes/), una por archivo.

## Opciones

| Opción | Por defecto | Qué hace |
|---|---|---|
| `publish` | apagada | Al final, después de `filter`, `ia.py publish` escribe cuerpos de issues y PRs y `publish/commands.sh` con los comandos `gh` exactos (cada uno con `--repo`; los PRs salen en borrador y referencian el issue sin cerrarlo; el push queda comentado). Nunca los corre |

## La carpeta de una corrida

Por defecto `<carpeta que contiene la raíz git del primer repo>/<sistema>-inherited-audit/<fecha>/`, fuera de los repos auditados.

| Contenido | Qué es |
|---|---|
| `manifest.json` | El estado: repos con su alias, commit y remoto; opciones; host; pasos; obreros; línea base; filtro. No se edita a mano: el plan de cada repo cambia con `ia.py baseline --set` y el resto (`host`, `lang`, `options.publish`, `sections`, `strengths`, `baseline.<ALIAS>.tests_branch`, `baseline.<ALIAS>.result.*`) con `ia.py set` |
| `findings/<id>.json` | Un archivo por hallazgo |
| `outputs/` | Salidas crudas: la suite de la base, la salida del test rojo de cada hallazgo de código y la del comando que confirma un hallazgo de cadena de suministro, contenedor o seguridad probado con un escáner. El verde y la suite por hallazgo son de corridas viejas: hoy no se escriben |
| `<sistema>-correctness.html`, `<sistema>-quality.html` | Los dos reportes |

## Un hallazgo

Ids `C-NN` (correctitud) y `Q-NN` (calidad). El detalle de cada campo está en
[`skill/references/schema.md`](../skill/references/schema.md).

| Cuándo | Campos obligatorios |
|---|---|
| Siempre | `id`, `report`, `category`, `dimension`, `title`, `verdict`, `severity`, `confidence`, `source`, `what_happens`, `evidence` (al menos una cita `ALIAS/ruta` con líneas) |
| Correctitud de código, confirmado por ejecución | Además `branch`, `sha_test`, `tests` y `red_reason` |
| Cadena de suministro o contenedor, confirmado por ejecución | Además `measurement.tool` y la salida guardada en `outputs/` |
| Calidad | Además `suggestion` y `effort` (`S`, `M` o `L`) |

`confidence` es `execution` (se corrió), `docs` (verificado contra documentación oficial o la API de la herramienta, sin correrlo) o `unverified` (no entra en los
reportes).

## Códigos de salida de `ia.py`

| Código | Significa |
|---|---|
| 0 | Salió bien |
| 1 | El comando encontró problemas (los imprime) |
| 2 | Error de uso |
| 3 | Una herramienta externa falló o no está |
| 4 | Falló `ia.py` mismo (un error que no esperaba): imprime una línea; con `IA_DEBUG=1`, el traceback. No hay que esquivarlo: se reporta |
| 128+N | Una señal N lo detuvo después de limpiar (143 SIGTERM, 129 SIGHUP, 130 Ctrl-C): se vuelve a correr |
