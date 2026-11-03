import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from catalog import products, store  # noqa: E402
from catalog.inventory import Inventory, OutOfStock  # noqa: E402
from checkout.flow import Checkout  # noqa: E402
from exports.files import Exports  # noqa: E402
from jobs.checkout_queue import CheckoutConsumer  # noqa: E402
from jobs.worker import Worker  # noqa: E402
from orders.service import Orders  # noqa: E402
from payments.client import PaymentsClient  # noqa: E402
from payments.money import format_cents, to_cents  # noqa: E402


class CatalogTest(unittest.TestCase):
    def setUp(self):
        self.conn = store.connect()
        store.add_product(self.conn, "L1", "Desk lamp", 2500, "2026-01-02")
        store.add_product(self.conn, "C1", "Chair", 9900, "2026-01-01")

    def test_search_by_name(self):
        self.assertEqual([p["sku"] for p in store.search(self.conn, "lamp")], ["L1"])

    def test_sorted_by_price(self):
        self.assertEqual([p["sku"] for p in store.list_sorted(self.conn, "price", descending=True)], ["C1", "L1"])

    def test_hidden_products_are_not_counted(self):
        store.set_hidden(self.conn, "C1", True)
        self.assertEqual(store.count_visible(self.conn), 1)

    def test_final_price_and_sale_label(self):
        p = products.make_product("L1", "Desk lamp", 2500, discount_pct=20)
        self.assertEqual(products.final_price_cents(p), 2000)
        self.assertIn("sale", products.label_set(p, []))


class InventoryTest(unittest.TestCase):
    def test_reserve_and_release(self):
        inv = Inventory({"L1": 2})
        inv.reserve("L1", 2)
        self.assertEqual(inv.available("L1"), 0)
        with self.assertRaises(OutOfStock):
            inv.reserve("L1", 1)
        inv.release("L1", 1)
        self.assertEqual(inv.available("L1"), 1)


class OrdersTest(unittest.TestCase):
    def test_place_list_and_get(self):
        orders = Orders()
        first = orders.place("ana", [{"sku": "L1", "qty": 1}])
        orders.place("ana", [{"sku": "C1", "qty": 2}])
        self.assertEqual(first["number"], 1)
        self.assertEqual(orders.list_for("ana", per_page=20)[0]["number"], 1)
        self.assertEqual(orders.get("ana", 1)["owner"], "ana")
        self.assertEqual(orders.total_cents(2, {"C1": 9900}), 19800)

    def test_cancel_then_pay_is_refused(self):
        orders = Orders()
        orders.place("ana", [])
        orders.cancel(1)
        with self.assertRaises(ValueError):
            orders.mark_paid(1, "ch_1")


class PaymentsTest(unittest.TestCase):
    def test_charge_on_first_try(self):
        class Transport:
            def post(self, path, payload):
                return {"id": "ch_1", "amount": payload["amount"], "status": "succeeded"}

        client = PaymentsClient(Transport(), sleep=lambda s: None)
        charge = client.charge(1, 2500, "tok_1")
        self.assertEqual(charge["id"], "ch_1")
        self.assertEqual(client.describe(charge), "charge ch_1 for 2500 cents is succeeded")

    def test_money(self):
        self.assertEqual(to_cents("12.34"), 1234)
        self.assertEqual(format_cents(-1205), "-12.05")


class WorkerTest(unittest.TestCase):
    def test_sends_one_email(self):
        sent = []

        class Queue:
            def __init__(self):
                self.items = [{"id": "m1", "to": "ana@example.com", "template": "welcome"}]

            def receive(self):
                return self.items.pop(0) if self.items else None

            def ack(self, message_id):
                pass

        class Mailer:
            def send(self, to, subject, data):
                sent.append((to, subject))

        self.assertEqual(Worker(Queue(), Mailer()).drain(), 1)
        self.assertEqual(sent, [("ana@example.com", "Welcome to the shop")])


class ExportsTest(unittest.TestCase):
    def test_write_read_and_list(self):
        with tempfile.TemporaryDirectory() as base:
            exports = Exports(base)
            exports.write_export("orders.csv", "number\n1\n")
            self.assertEqual(exports.read_export("orders.csv"), "number\n1\n")
            self.assertEqual(exports.list_exports(), ["orders.csv"])
            os.mkdir(os.path.join(base, "reports"))
            with open(os.path.join(base, "reports", "q1.txt"), "w", encoding="utf-8") as fh:
                fh.write("ok")
            self.assertEqual(exports.read_report("q1.txt"), "ok")



class CheckoutTest(unittest.TestCase):
    def shop(self):
        class Transport:
            def post(self, path, payload):
                return {"id": "ch_1", "status": "succeeded"}

        inventory = Inventory({"L1": 3})
        return Checkout(Orders(), inventory, PaymentsClient(Transport()), {"L1": 2500}), inventory

    def test_submit_pays_the_order_and_takes_the_stock(self):
        checkout, inventory = self.shop()
        order = checkout.submit("ana", [{"sku": "L1", "qty": 2}], "tok")
        self.assertEqual((order["status"], order["charge_id"]), ("paid", "ch_1"))
        self.assertEqual(inventory.available("L1"), 1)

    def test_cancel_gives_the_stock_back(self):
        checkout, inventory = self.shop()
        order = checkout._orders.place("ana", [{"sku": "L1", "qty": 2}])
        inventory.reserve("L1", 2)
        checkout.cancel(order["number"])
        self.assertEqual(inventory.available("L1"), 3)

    def test_consumer_handles_one_request(self):
        checkout, _ = self.shop()
        acked = []

        class Queue:
            def receive(self):
                return {"id": "m1", "request_id": "r1", "owner": "ana", "items": [{"sku": "L1", "qty": 1}],
                        "card": "tok"}

            def ack(self, message_id):
                acked.append(message_id)

        self.assertTrue(CheckoutConsumer(Queue(), checkout).run_once())
        self.assertEqual(acked, ["m1"])

if __name__ == "__main__":
    unittest.main()
