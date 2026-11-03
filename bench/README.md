# Banco de prueba: workers contra pases de respaldo

Un sistema chico (una tienda en Python, solo biblioteca estándar) con **diez problemas** (nueve sembrados y uno
que encontró una corrida) y **seis señuelos**, más la clave para medir con `ia.py eval` cuántos encuentra una auditoría y cuántos falsos positivos marca.
Sirve para comparar, sobre el mismo commit, una corrida con los workers externos (`/code-review`, `claude-security`,
`feature-dev`) contra otra con los pases de respaldo de la skill.

## Qué hay

| Ruta | Qué es |
|---|---|
| `seeded/` | El código del sistema. Es lo único que ve el auditor: no tiene comentarios ni nombres que delaten los problemas |
| `build.py` | Lo convierte en un repo git con un commit fijo (`sha` de `key.json`) |
| `key.json` | La clave: ítems con su `area`, señuelos, `pass_at` y `max_decoy_hits` |
| `proofs/` | Una prueba por ítem (falla en ese commit) y una por señuelo (pasa). `tests/test_bench.py` lo verifica |

Áreas de los ítems y quién las cubre:

| `area` | Ítems | Worker en Claude Code | Respaldo |
|---|---|---|---|
| `correctness-general` | C1, C2 | `/code-review` | `references/passes/correctness-general.md` |
| `security` | S1, S2, S3 | `claude-security` | `references/passes/security.md` |
| `quality-lenses` | C3 | `feature-dev:code-architect` | `references/passes/quality-lenses.md` |
| `races-distributed` | R1, R2, R3 | ninguno | `references/passes/races-distributed.md` |

Ojo con `races-distributed`: no hay worker externo que lo cubra, así que esos tres ítems miden **solo** el pase propio.
No los leas como una comparación entre worker y respaldo.

## Cómo correr una comparación

1. Construí el repo fuera de este repo:

   ```bash
   python3 bench/build.py ~/bench-runs/shop
   ```

   Imprime el sha; tiene que ser el de `key.json`. El script deja afuera tu config global de git solo para ese repo
   nuevo (tus hooks y tu firma cambiarían el commit): es el mismo aislamiento que usan los tests.

2. Abrí la sesión de la auditoría **parado en `~/bench-runs/shop`, no en este repo**. Un agente con la carpeta de
   este repo a mano puede leer la clave y las pruebas, y la medición deja de valer.

3. Corré la auditoría con la skill, con el alias `SHOP` (es el que usa la clave):

   ```bash
   python3 <skill-dir>/ia.py init --system shop --repo SHOP=$HOME/bench-runs/shop --host claude-code \
     --out ~/bench-runs/con-workers
   ```

   Para la corrida de respaldo, otra carpeta (`--out ~/bench-runs/respaldo`). Declinar los workers en el paso 0 solo
   alcanza para los que faltan; si están instalados, después de `ia.py detect` marcá cada fila externa como no
   disponible, con el paso y el nombre exactos que imprime la tabla de `detect`:

   ```bash
   python3 <skill-dir>/ia.py set --run ~/bench-runs/respaldo 'workers.claude-code.<paso>.<worker>.available=false'
   ```

   Así ese paso usa su pase de respaldo. Decíselo también al agente que orquesta, para que no los invoque igual.

4. Medí cada corrida:

   ```bash
   python3 <skill-dir>/ia.py eval --run ~/bench-runs/con-workers --reference bench/key.json
   python3 <skill-dir>/ia.py eval --run ~/bench-runs/respaldo --reference bench/key.json
   ```

   Muestra lo encontrado y lo que faltó, los señuelos tocados y el desglose por área. Cada par hallazgo-ítem es un
   candidato: confirmalo leyendo los dos.

## Cómo leer el resultado

- **Una corrida por lado es ruido.** Un modelo no da lo mismo dos veces. Hacé al menos tres por lado y compará los
  rangos, no un número suelto.
- **Mirá encontrados y falsos positivos juntos.** Un pase que marca todo sube lo encontrado y toca señuelos.
- **El banco está sesgado.** Los problemas los sembró la misma familia de modelos que escribió los pases de respaldo,
  y son patrones conocidos en un sistema chico. Sirve para comparar dos lados sobre la misma clave, no como medida
  absoluta de lo que encuentra una auditoría en un sistema real.
- `pass_at` (7 de 10) y `max_decoy_hits` (1) son un primer corte elegido a ojo, no un estándar.
- **R4 no se sembró:** lo encontró la primera corrida de respaldo y se sumó con su prueba. `total_size`
  (`files.py` 31-32) tiene otra carrera real que quedó fuera de la clave porque está a menos de 15 líneas de D6:
  una corrida que la reporta acierta, y el puntaje la ignora. Se suma cuando el próximo cambio del sha separe los dos.
- **Un hallazgo que cuenta para un ítem nunca es falso positivo**, aunque cite un señuelo: lo cita como contraste.

## Si cambiás el banco

Cualquier cambio en `seeded/` cambia el sha y puede mover las líneas. Corré `python3 bench/build.py <carpeta-vacía>`,
actualizá `sha` y las `cites` de `key.json`, y después `python3 -m unittest tests.test_bench` (desde la raíz:
`python3 -m unittest discover -s tests -p test_bench.py`). Ese test falla si el sha no coincide, si una cita cae
fuera del archivo, si un ítem deja de fallar, si un señuelo deja de pasar o si algo en el código auditado nombra la
clave.
