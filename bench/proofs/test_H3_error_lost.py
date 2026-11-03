import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.environ["BENCH_REPO"], "src"))
from catalog.inventory import Inventory
from checkout.flow import Checkout
from orders.service import Orders
from payments.client import GatewayTimeout, PaymentsClient


class Proof(unittest.TestCase):
    def test_a_gateway_error_reaches_the_caller(self):
        class Transport:
            def post(self, path, payload):
                raise GatewayTimeout()

        orders = Orders()
        order = orders.place("ana", [{"sku": "A", "qty": 1}])
        attempts = []
        checkout = Checkout(orders, Inventory({"A": 5}), PaymentsClient(Transport(), sleep=lambda s: None),
                            {"A": 100}, attempts)
        raised = False
        try:
            checkout.pay_again(order["number"], "tok")
        except GatewayTimeout:
            raised = True
        self.assertEqual(attempts, [(order["number"], "failed")])
        self.assertTrue(raised, "pay_again returned instead of raising the gateway error")


if __name__ == "__main__":
    unittest.main()
