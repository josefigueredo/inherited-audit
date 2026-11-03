import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.environ["BENCH_REPO"], "src"))
from catalog.inventory import Inventory
from checkout.flow import Checkout
from orders.service import Orders
from payments.client import PaymentsClient


class Proof(unittest.TestCase):
    def test_cancel_gives_back_exactly_what_the_order_held_once(self):
        inventory = Inventory({"A": 5, "B": 3})
        orders = Orders()
        checkout = Checkout(orders, inventory, PaymentsClient(None), {"A": 100, "B": 100})
        order = orders.place("ana", [{"sku": "A", "qty": 2}, {"sku": "B", "qty": 3}])
        inventory.reserve("A", 2)
        inventory.reserve("B", 3)
        checkout.cancel(order["number"])
        self.assertEqual((inventory.available("A"), inventory.available("B")), (5, 3))
        with self.assertRaises(ValueError):
            checkout.cancel(order["number"])
        self.assertEqual((inventory.available("A"), inventory.available("B")), (5, 3))


if __name__ == "__main__":
    unittest.main()
