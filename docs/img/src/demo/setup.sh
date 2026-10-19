#!/usr/bin/env bash
# Builds the showcase fixture: a fake HOME with the skill installed and a tiny git repo "tienda" with a real bug.
set -euo pipefail
# Usage: docs/img/src/demo/setup.sh <empty-dir>   (then build the captures with HOME=<empty-dir>/home)
S="$1"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_SRC="$(cd "$HERE/../../../.." && pwd)"
[ ! -e "$S/home" ] || { echo "refusing: $S/home already exists" >&2; exit 1; }
D="$S/home/demo"
mkdir -p "$D/tienda/tienda" "$D/tienda/tests"
export GIT_AUTHOR_NAME=Demo GIT_AUTHOR_EMAIL=demo@example.com GIT_COMMITTER_NAME=Demo GIT_COMMITTER_EMAIL=demo@example.com
export GIT_AUTHOR_DATE=2026-10-18T12:00:00+00:00 GIT_COMMITTER_DATE=2026-10-18T12:00:00+00:00
cd "$D/tienda"
: > tienda/__init__.py
echo "__pycache__/" > .gitignore
cat > tienda/carrito.py <<'P'
def total(items, cupon_pct=0):
    """Suma precio por cantidad y aplica un cupón en porcentaje."""
    bruto = sum(precio * cantidad for precio, cantidad in items)
    return bruto - bruto * cupon_pct / 100


def total_con_envio(items, cupon_pct=0):
    bruto = sum(precio * cantidad for precio, cantidad in items)
    neto = bruto - bruto * cupon_pct / 100
    return neto + (0 if neto > 100 else 10)
P
: > tests/__init__.py
cat > tests/test_carrito.py <<'P'
import unittest

from tienda.carrito import total


class TotalTest(unittest.TestCase):
    def test_suma_items(self):
        self.assertEqual(total([(10, 2), (5, 1)]), 25)

    def test_cupon_del_diez(self):
        self.assertEqual(total([(100, 1)], cupon_pct=10), 90)
P
git init -q -b main && git add -A && git -c commit.gpgsign=false commit -q -m "tienda: carrito"
git checkout -q -b fix/c-01-cupon-mayor-a-cien
cat > tests/test_cupon_tope.py <<'P'
import unittest

from tienda.carrito import total


class CuponTopeTest(unittest.TestCase):
    def test_un_cupon_de_mas_del_cien_no_deja_el_total_negativo(self):
        self.assertGreaterEqual(total([(100, 1)], cupon_pct=150), 0)
P
git add -A && git -c commit.gpgsign=false commit -q -m "test: un cupón de más del 100% deja el total negativo"
git checkout -q main
HOME="$S/home" bash "$REPO_SRC/install.sh" >/dev/null
cp "$HERE"/*.json "$D/"
