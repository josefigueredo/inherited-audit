import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.environ["BENCH_REPO"], "src"))

from catalog import store


class Proof(unittest.TestCase):
    def test_sort_accepts_only_known_keys(self):
        conn = store.connect()
        store.add_product(conn, "L1", "Desk lamp", 2500, "2026-01-01")
        with self.assertRaises(KeyError):
            store.list_sorted(conn, "price; DROP TABLE products")
        self.assertEqual(store.count_visible(conn), 1)


if __name__ == "__main__":
    unittest.main()
