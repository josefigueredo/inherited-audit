import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.environ["BENCH_REPO"], "src"))

from catalog.products import label_set, make_product


class Proof(unittest.TestCase):
    def test_labels_do_not_leak_between_products(self):
        label_set(make_product("A", "a", 100, discount_pct=10))
        self.assertEqual(label_set(make_product("B", "b", 100)), [])


if __name__ == "__main__":
    unittest.main()
