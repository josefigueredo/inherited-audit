import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.environ["BENCH_REPO"], "src"))
from catalog.inventory import Inventory, OutOfStock
from checkout.flow import Checkout
from orders.service import Orders
from payments.client import PaymentsClient


class Proof(unittest.TestCase):
    def test_a_cart_that_cannot_be_filled_takes_no_stock(self):
        inventory = Inventory({"A": 5, "B": 0})
        checkout = Checkout(Orders(), inventory, PaymentsClient(None), {"A": 100, "B": 100})
        with self.assertRaises(OutOfStock):
            checkout.submit("ana", [{"sku": "A", "qty": 2}, {"sku": "B", "qty": 1}], "tok")
        self.assertEqual(inventory.available("A"), 5)


if __name__ == "__main__":
    unittest.main()
