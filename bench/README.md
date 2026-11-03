# Banco de prueba: workers contra pases de respaldo

Un sistema chico (una tienda en Python, solo biblioteca estándar) con **catorce problemas** y **siete señuelos**, más la
clave para medir con `ia.py eval` cuántos encuentra una auditoría y cuántos falsos positivos marca. Sirve para comparar,
sobre el mismo commit, una corrida con los workers externos (`/code-review`, `claude-security`, `feature-dev`) contra
otra con los pases de respaldo de la skill.

Los problemas son de dos niveles:

- **Diez de manual** (C, R, S): se ven leyendo una función. La versión 1 del banco tenía solo estos, y los dos lados
  sacaron 10/10: no sirven para distinguirlos.
- **Cuatro difíciles** (H1 a H4): para verlos hay que leer más de una función, y para H2 a H4 más de un módulo: el
  contrato de la cola, cómo el cliente de pagos maneja un timeout, el handler de la tienda y los helpers de plata.
  Ningún docstring ni linter los señala. **Son la medida principal.**

## Qué hay

| Ruta | Qué es |
|---|---|
| `seeded/` | El código del sistema. Es lo único que ve el auditor: no tiene comentarios ni nombres que delaten los problemas |
| `build.py` | Lo convierte en un repo git con un commit fijo (`sha` de `key.json`) |
| `key.json` | La clave: ítems con su `area`, señuelos, `pass_at`, `max_decoy_hits` y, en `notes`, la medida fijada de antemano |
| `proofs/` | Una prueba por ítem (falla en ese commit) y una por señuelo (pasa). `tests/test_bench.py` lo verifica |

Áreas de los ítems y quién las cubre:

| `area` | Ítems | Worker en Claude Code | Respaldo |
|---|---|---|---|
| `correctness-general` | C1, C2, H1, H3, H4 | `/code-review` | `references/passes/correctness-general.md` |
| `security` | S1, S2, S3 | `claude-security` | `references/passes/security.md` |
| `quality-lenses` | C3 | `feature-dev:code-architect` | `references/passes/quality-lenses.md` |
| `races-distributed` | R1, R2, R3, R4, H2 | ninguno | `references/passes/races-distributed.md` |

Ojo con `races-distributed`: no hay worker externo que lo cubra, así que esos ítems miden **solo** el pase propio. No los
leas como una comparación entre worker y respaldo.

## Cómo correr una comparación

1. **Un repo nuevo por corrida**, fuera de este repo:

   ```bash
   python3 bench/build.py ~/bench-runs/shop-<corrida>
   ```

   Imprime el sha; tiene que ser el de `key.json`. Cada corrida deja ramas en el repo que audita (una por hallazgo),
   con nombres que dicen qué encontró: una segunda corrida en el mismo repo vería las respuestas de la primera. El
   script deja afuera tu config global de git solo para ese repo nuevo (tus hooks y tu firma cambiarían el commit).

2. **Archivá las corridas terminadas fuera de `~/bench-runs`** (por ejemplo en `~/bench-archive/`), con su repo. Una
   sesión nueva no tiene que tener a mano los hallazgos de otra. `ia.py eval --run <ruta-nueva>` sigue funcionando.

3. Abrí la sesión de la auditoría **parado en `~/bench-runs/shop-<corrida>`, no en este repo**. Un agente con la carpeta
   de este repo a mano puede leer la clave y las pruebas, y la medición deja de valer.

4. Corré la auditoría con la skill, con el alias `SHOP` (es el que usa la clave) y en inglés:

   ```bash
   python3 <skill-dir>/ia.py init --system shop --repo SHOP=$HOME/bench-runs/shop-<corrida> --host claude-code \
     --lang en --out ~/bench-runs/<corrida>
   ```

   `--lang` decide el idioma de los reportes, no el del texto de cada hallazgo. Por eso el prompt de la corrida también
   tiene que decir: «Escribí el título y el `what_happens` de cada hallazgo en inglés». Las palabras de la clave están
   solo en inglés: en la versión 1, una corrida que escribió en castellano dio 4/10 sin haber encontrado menos.

   Para la corrida de respaldo, después de `ia.py detect` marcá cada fila externa como no disponible, con el paso y el
   nombre exactos que imprime la tabla de `detect`. Para la de workers, marcalas como disponibles (`=true`), así las
   dos difieren solo en eso:

   ```bash
   python3 <skill-dir>/ia.py set --run ~/bench-runs/<corrida> 'workers.claude-code.<paso>.<worker>.available=false'
   ```

   Decíselo también al agente que orquesta: en respaldo, que no los invoque; en workers, que avise si uno falla en vez
   de seguir con el respaldo sin decir nada.

5. **Antes de cerrar la sesión, guardá su `/cost`** en `~/bench-runs/<corrida>/cost.txt`. Sin eso no hay comparación de
   costo, y no se recupera después: el transcript no registra todo lo que suma `/cost`.

6. Medí cada corrida:

   ```bash
   python3 <skill-dir>/ia.py eval --run ~/bench-runs/<corrida> --reference bench/key.json
   ```

   Muestra lo encontrado y lo que faltó, los señuelos tocados y el desglose por área. Cada par hallazgo-ítem es un
   candidato: confirmalo leyendo los dos.

**Orden recomendado:** primero una corrida de respaldo, que es la más barata. Si encuentra los cuatro difíciles, el banco
sigue saturado y hay que rediseñarlo antes de gastar en la de workers.

## Cómo leer el resultado

- **Medida principal, fijada antes de correr:** cuántos de H1 a H4 encuentra cada lado. Después, los falsos positivos.
  Después, el costo.
- **Una corrida por lado es ruido.** Un modelo no da lo mismo dos veces. Hacé al menos tres por lado y compará los
  rangos, no un número suelto.
- **Mirá encontrados y falsos positivos juntos.** Un pase que marca todo sube lo encontrado y toca señuelos.
- **Un hallazgo que cuenta para un ítem nunca es falso positivo**, aunque cite un señuelo: lo cita como contraste.
- **El banco está sesgado.** Los problemas los sembró la misma familia de modelos que escribió los pases de respaldo, y
  el sistema es chico. Sirve para comparar dos lados sobre la misma clave, no como medida absoluta.
- `pass_at` (9 de 14) y `max_decoy_hits` (1) son un primer corte elegido a ojo, no un estándar.
- **R4 no se sembró:** lo encontró una corrida de la versión 1 y se sumó con su prueba. Otros seis defectos que nadie
  sembró y que encontraron las corridas de la versión 1 están arreglados en la versión 2, para que no ensucien la
  cuenta de hallazgos extra.

## Historia

| Versión | sha | Ítems | Resultado |
|---|---|---|---|
| 1 | `605d764` | 10 (9 sembrados + R4) | respaldo y workers: 10/10, 0 señuelos. Corrección confirmados: 11 de 14 (respaldo) contra 17 de 19 (workers). Calidad: respaldo dejó sus 10 en candidato; workers confirmó 11. Workers costó $23,34; el costo de respaldo no se guardó (por tokens, ~55–65% de eso, una inferencia) |
| 2 | ver `key.json` | 14 (+ H1 a H4) | sin corridas todavía |

`ia.py eval` rechaza una corrida de otra versión (`check_sha`); para volver a medir una de la versión 1, usá la clave
de esa versión desde git (`git show <commit>:bench/key.json`).

## Si cambiás el banco

Cualquier cambio en `seeded/` cambia el sha y puede mover las líneas. Corré `python3 bench/build.py <carpeta-vacía>`,
actualizá `sha` y las `cites` de `key.json`, y después `python3 -m unittest discover -s tests -p test_bench.py` desde la
raíz. Ese test falla si el sha no coincide, si una cita cae fuera del archivo, si un ítem deja de fallar, si un señuelo
deja de pasar o si algo en el código auditado nombra la clave. Cada prueba nueva de un ítem tiene que fallar por una
aserción con el problema y pasar con el arreglo: probalo contra una copia arreglada antes de sumarla.
