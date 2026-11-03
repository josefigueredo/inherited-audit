import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.environ["BENCH_REPO"], "src"))

from catalog.inventory import Inventory
from checkout.flow import Checkout
from orders.service import Orders
from payments.client import GatewayTimeout, PaymentsClient
from storefront.handlers import retry_payment


class Proof(unittest.TestCase):
    def test_a_buyer_retrying_while_the_gateway_is_down_is_told_to_try_later(self):
        class Transport:
            def post(self, path, payload):
                raise GatewayTimeout()

        orders = Orders()
        order = orders.place("ana", [{"sku": "A", "qty": 1}])
        checkout = Checkout(orders, Inventory({"A": 5}), PaymentsClient(Transport(), sleep=lambda s: None), {"A": 100})
        try:
            answer = retry_payment(checkout, order["number"], "tok")
        except TypeError as exc:
            answer = {"status": f"crashed: {exc}"}
        self.assertEqual(answer["status"], 503)


if __name__ == "__main__":
    unittest.main()
