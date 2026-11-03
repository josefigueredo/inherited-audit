import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.environ["BENCH_REPO"], "src"))
from catalog.inventory import Inventory
from checkout.flow import Checkout
from jobs.checkout_queue import CheckoutConsumer
from orders.service import Orders
from payments.client import PaymentsClient


class Proof(unittest.TestCase):
    def test_a_request_delivered_twice_is_charged_once(self):
        posts = []

        class Transport:
            def post(self, path, payload):
                posts.append(payload)
                return {"id": f"ch_{len(posts)}", "status": "succeeded"}

        message = {"id": "m1", "request_id": "r1", "owner": "ana", "items": [{"sku": "A", "qty": 1}], "card": "tok"}

        class Queue:
            def __init__(self):
                self.pending = [message, dict(message, id="m1-again")]  # the first ack came too late

            def receive(self):
                return self.pending.pop(0) if self.pending else None

            def ack(self, message_id):
                pass

        orders = Orders()
        checkout = Checkout(orders, Inventory({"A": 5}), PaymentsClient(Transport()), {"A": 100})
        consumer = CheckoutConsumer(Queue(), checkout)
        while consumer.run_once():
            pass
        self.assertEqual(len(posts), 1)
        self.assertEqual(len(orders.list_for("ana")), 1)


if __name__ == "__main__":
    unittest.main()
