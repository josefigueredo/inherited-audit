import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.environ["BENCH_REPO"], "src"))

from catalog import store


class Proof(unittest.TestCase):
    def test_search_text_cannot_reveal_hidden_products(self):
        conn = store.connect()
        store.add_product(conn, "L1", "Desk lamp", 2500, "2026-01-01")
        store.add_product(conn, "X1", "Unreleased prototype", 1, "2026-01-01", hidden=True)
        found = store.search(conn, "x' OR hidden = 1 --")
        self.assertNotIn("X1", [p["sku"] for p in found])


if __name__ == "__main__":
    unittest.main()
