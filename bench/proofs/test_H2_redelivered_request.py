import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.environ["BENCH_REPO"], "src"))

from catalog.inventory import Inventory
from checkout.flow import Checkout
from jobs.checkout_queue import CheckoutConsumer
from jobs.leased_queue import LeasedQueue
from orders.service import Orders
from payments.client import PaymentsClient
from storefront.handlers import enqueue_checkout


class Proof(unittest.TestCase):
    def test_a_checkout_request_is_charged_once_even_when_the_gateway_is_slow(self):
        now = [0.0]
        posts = []

        class Transport:
            def post(self, path, payload):
                posts.append(payload)
                if len(posts) == 1:
                    now[0] += 31  # the first answer takes longer than the lease
                return {"id": f"ch_{len(posts)}", "status": "succeeded"}

        queue = LeasedQueue(lease_seconds=30, clock=lambda: now[0])
        orders = Orders()
        checkout = Checkout(orders, Inventory({"A": 5}), PaymentsClient(Transport()), {"A": 100})
        enqueue_checkout(queue, "ana", [{"sku": "A", "qty": 1}], "tok")
        consumer = CheckoutConsumer(queue, checkout)
        while consumer.run_once():
            pass
        self.assertEqual(len(posts), 1)
        self.assertEqual(len(orders.list_for("ana")), 1)


if __name__ == "__main__":
    unittest.main()
