import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.environ["BENCH_REPO"], "src"))
from catalog.inventory import Inventory
from checkout.flow import Checkout
from orders.service import Orders
from payments.client import PaymentsClient


class Proof(unittest.TestCase):
    def test_the_card_is_charged_the_order_total(self):
        posts = []

        class Transport:
            def post(self, path, payload):
                posts.append(payload)
                return {"id": "ch_1", "status": "succeeded"}

        checkout = Checkout(Orders(), Inventory({"A": 5}), PaymentsClient(Transport()), {"A": 2500})
        checkout.submit("ana", [{"sku": "A", "qty": 2}], "tok")
        self.assertEqual(posts[0]["amount"], 5000)


if __name__ == "__main__":
    unittest.main()
