# Referencia

Para consultar: el checklist, las opciones, la carpeta de una corrida, los campos de un hallazgo y los códigos de
salida. La fuente de verdad es lo que lee el agente, en inglés: [`skill/SKILL.md`](../skill/SKILL.md) y
[`skill/references/`](../skill/references/). Esto es un resumen para personas.

## El checklist

Once pasos, en este orden; cada uno queda en `manifest.json` como `pending`, `in_progress`, `done` o `skipped`, y
`ia.py status` dice cuál sigue.

| Paso | Qué produce | Se cierra cuando |
|---|---|---|
| `baseline` | Commit fijado, inventario del sistema, suite medida, workers disponibles | `ia.py baseline` tiene resultado para cada repo; un repo sin comando de tests queda abierto hasta que registrás el resultado a mano con `ia.py set` (`baseline.<ALIAS>.result.passed`, `failed`, `total`…; `total=0` si no tiene runner) |
| `correctness` | Candidatos de bugs, races, sistemas distribuidos, seguridad, cadena de suministro y contenedor, con citas en la base | El agente lo marca hecho |
| `proof` | Una rama local por candidato con un commit de solo tests, rojo por una aserción; o descartado con motivo | Todas las ramas combinan de a pares (`merge-check`) |
| `tests` | Tests unitarios y e2e que faltaban, verdes en la base, en una rama aparte por repo | Esa rama combina con las de los hallazgos |
| `quality` | Hallazgos de calidad y arquitectura, cada uno con sugerencia, esfuerzo y, si es un número, la medición | El agente lo marca hecho |
| `contrast` | Veredicto de otro modelo (`agree`, `refute`, `unsure`) sobre cada hallazgo | Lo refutado se rebatió con evidencia o se descartó |
| `verify` | Cada severidad alta re-verificada por un subagente nuevo | El agente lo marca hecho |
| `filter` | Qué ve el equipo dueño y los conteos «N de M» | `ia.py filter` |
| `prose` | Título, qué pasa y arreglo en el idioma del reporte, sin jerga ni culpas | El agente lo marca hecho, después del control de términos prohibidos |
| `hygiene` | Ramas y salidas sin secretos ni archivos locales, sin atribución a un LLM en los commits de las ramas ni en los archivos de publicación, corrida no commiteable | `ia.py hygiene` da limpio (`--fix` antes enmascara las salidas guardadas, los archivos de publicación y la prosa de los hallazgos) |
| `render` | Los dos HTML | `ia.py render` |

## Workers por host

Regla: un worker externo donde exista y sea bueno; una pasada propia de la skill donde no haya nada. Algunos ejemplos;
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
| `publish` | apagada | Al final, después de `filter`, `ia.py publish` escribe cuerpos de issues y PRs y `publish/commands.sh` con los comandos `gh` exactos (cada uno con `--repo`; los PRs salen en borrador y referencian el issue sin cerrarlo; el push queda comentado; cada issue creado imprime su número; issues y PRs llevan labels según la dimensión, que el script crea antes en cada repo, y el título de cada PR es el asunto del commit con el test rojo, en conventional commits). Un hallazgo con rama manda su issue al repo de su rama (su primera cita), el mismo de su PR; uno sin rama, al de `publish_repo` si lo tiene, si no al repo más citado, con un comentario en `commands.sh` para revisarlo cuando cita varios. Nunca los corre |

## Después de la auditoría: arreglos (inherited-fix)

La auditoría se detiene en el test rojo. Arreglar un hallazgo ya publicado es una decisión posterior, del equipo dueño, y
la lleva la skill compañera `inherited-fix` (carpeta `fix-skill/`; `install.sh` la enlaza al lado de esta). Usa el mismo
CLI:

| Acción | Qué hace |
|---|---|
| `ia.py fix plan` | Lista las ramas de PR para arreglar, con el número de PR y su base (con `gh` de solo lectura) y los hallazgos de cada una. Un PR de grupo (`audit/pr-N`) se arregla entero, en orden, en un solo worktree |
| `ia.py fix start` | Crea el worktree en la rama del PR y el contexto de cada hallazgo. Corre la suite sobre un merge descartable de la base del PR y guarda los tests que pasan, por nombre (por conteo si no hay junit, y lo dice). Un hallazgo que ya pasa ahí queda `moot`. Necesita `fix.authorized_by` en el manifest |
| `ia.py fix check` | Revisa los commits del arreglo: el test rojo intacto, el alcance (`prod_files`, `fix.extra_files`, tests nuevos), conventional commits de 100 caracteres o menos, sin palabra de cierre, atribución ni rutas locales, e higiene. Corre la suite sobre el merge y la compara con la del inicio |
| `ia.py fix done` | Registra el arreglo solo con el chequeo y una revisión de otro agente con tres afirmaciones CONFIDENT sobre el mismo commit. Un `blocked` o `declined` vuelve atrás la rama local |
| `ia.py fix publish` | Escribe `fix/commands.sh`: push sin forzar, el PR resuelto al correr, el cuerpo actual reescrito (nota de borrador → nota de arreglo, `Refs` → `Closes`), el título del commit de arreglo y `gh pr ready`. Con `--partial`, un grupo incompleto sube lo arreglado y sigue en borrador. Nunca lo corre |

## La carpeta de una corrida

Por defecto `<carpeta que contiene la raíz git del primer repo>/<sistema>-inherited-audit/<fecha>/`, fuera de los repos auditados.

| Contenido | Qué es |
|---|---|
| `manifest.json` | El estado: repos con su alias, commit y remoto; opciones; host; pasos; workers; línea base; filtro. No se edita a mano: el plan de cada repo cambia con `ia.py baseline --set` y el resto (`host`, `lang`, `options.publish`, `sections`, `strengths`, `baseline.<ALIAS>.tests_branch`, `baseline.<ALIAS>.result.*`, `fix.authorized_by`) con `ia.py set` |
| `findings/<id>.json` | Un archivo por hallazgo |
| `outputs/` | Salidas crudas: la suite de la base, la salida del test rojo de cada hallazgo de código y la del comando que confirma un hallazgo de cadena de suministro, contenedor o seguridad probado con un escáner. El verde y la suite por hallazgo los escribe solo `ia.py fix` (`<id>-green.txt`, `<id>-fix-red.txt`, `<id>-fix-suite.txt`) |
| `fix/` | Lo de inherited-fix: un worktree por rama de PR (`wt-*`), el contexto y el estado de cada rama y `commands.sh` |
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
