import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.environ["BENCH_REPO"], "src"))

from orders.service import Orders


class Proof(unittest.TestCase):
    def test_a_full_page_has_per_page_orders(self):
        orders = Orders()
        for _ in range(3):
            orders.place("ana", [])
        self.assertEqual([o["number"] for o in orders.list_for("ana", page=1, per_page=3)], [1, 2, 3])


if __name__ == "__main__":
    unittest.main()
