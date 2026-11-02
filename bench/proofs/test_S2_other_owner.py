import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.environ["BENCH_REPO"], "src"))

from orders.service import Orders


class Proof(unittest.TestCase):
    def test_a_user_cannot_read_another_users_order(self):
        orders = Orders()
        orders.place("ana", [{"sku": "L1", "qty": 1}])
        with self.assertRaises(PermissionError):
            orders.get("bob", 1)


if __name__ == "__main__":
    unittest.main()
