# Instalación y primer uso, conversando con tu agente

Todo se hace pidiéndoselo al agente, en Claude Code o en Cursor. Si preferís los comandos, está la
[instalación detallada](instalacion-detallada.md); para cada caso entero, el [showcase](showcase.md).

## 1. Instalar

Decile al agente, en cualquiera de los dos:

> *«Instalá la skill inherited-audit desde <ruta-a-tu-clon>/inherited-audit»*

Corre `./install.sh`, que enlaza solo la carpeta `skill/` en `~/.claude/skills/inherited-audit`. Esa única carpeta
sirve para los dos hosts: Cursor también lee `~/.claude/skills` por compatibilidad. Por eso el instalador no escribe
nada en `~/.agents/skills`: Cursor vería la skill dos veces.

Si solo usás Cursor, pedile *«Instalá la skill inherited-audit solo para Cursor»*: corre `./install.sh --cursor`, que la
enlaza en `~/.cursor/skills/inherited-audit` en vez de `~/.claude/skills`. Va en una de las dos carpetas, nunca en las
dos: si encuentra la otra, no enlaza nada, avisa que Cursor la cargaría dos veces y sale con 1.

Si una sesión que ya estaba abierta no encuentra la skill, cerrala y abrila de nuevo.

## 2. Auditar desde Claude Code

> *«Auditá el sistema tienda antes de que empecemos: el back está en ~/w/tienda-api y el front en ~/w/tienda-web»*

El agente detecta que corre en Claude Code, crea la corrida al lado del primer repo
(`~/w/tienda-inherited-audit/<fecha>/`), fija el commit de cada repo y mide la suite. Antes de seguir te muestra los
obreros que faltan (por ejemplo semgrep o un plugin de revisión) con su comando de instalación, y te pregunta **una sola
vez** cuáles querés. Lo que no instales lo cubre una pasada propia de la skill durante toda la corrida.

Si un repo tiene cambios sin commitear, la corrida no arranca: el agente te pregunta si los commitea o los guarda
aparte. Si no le dijiste nada sobre `publish` (dejar listos los cuerpos de issues y PRs), te pregunta; viene apagado. La
skill nunca arregla el código: cada hallazgo confirmado termina en una rama con el test en rojo y la propuesta
escrita.

## 3. Auditar desde Cursor

En el chat del agente de Cursor, el mismo pedido:

> *«Auditá el sistema tienda antes de que empecemos: el back está en ~/w/tienda-api y el front en ~/w/tienda-web»*

El agente detecta que corre en Cursor y usa los obreros de Cursor en cada paso (por ejemplo `/review-bugbot` para los
bugs generales y otro modelo con `agent` para el contraste). El checklist, los hallazgos y los reportes son los mismos.

## 4. Retomar una corrida

Una auditoría real lleva horas y no entra en una sesión. Para seguir, en cualquiera de los dos hosts:

> *«Retomá la auditoría de tienda»*

El agente corre `ia.py status`, lee qué pasos están hechos y sigue en el primero pendiente. Si empezaste en Claude Code
y seguís en Cursor, desde ahí usa los obreros de Cursor; las opciones que elegiste al principio no se vuelven a
preguntar.

## 5. Sumar los subagentes opcionales

La skill no los necesita: lanza un subagente genérico con la ruta de la pasada. Si querés uno con nombre:

> *«Instalá inherited-audit con los subagentes opcionales»*

Corre `./install.sh --agents`, que además enlaza `ia-auditor` en `~/.claude/agents/` (Claude Code) y en
`~/.cursor/agents/` (Cursor). Con `--cursor --agents`, solo en `~/.cursor/agents/`. En Cursor es de solo lectura, para
las pasadas de análisis.

## Si algo falla

| Situación | Qué hacer |
|---|---|
| El instalador dice `refusing to replace …` | Ya hay una carpeta o un archivo de verdad con ese nombre. Movelo a otro lado y pedile que instale de nuevo |
| `init` no arranca porque un repo tiene cambios | Commitealos o guardalos aparte (el agente te pregunta antes) |
| `init` dice que la carpeta de salida se puede commitear | Pedile otra carpeta, fuera de cualquier repo: los reportes llevan hallazgos de seguridad |
| `cite-check` marca una cita | El hallazgo cita un archivo o unas líneas que no existen en el commit fijado; el agente lo corrige antes de armar los reportes |
| La skill aparece dos veces en Cursor | Hay otra copia en `~/.agents/skills/inherited-audit` o en el proyecto, o está en `~/.claude/skills` y en `~/.cursor/skills`; dejá una sola |

## De dónde sale cada captura

Esta guía no tiene capturas: las de la instalación y de una corrida están en la
[instalación detallada](instalacion-detallada.md#de-dónde-sale-cada-captura).
