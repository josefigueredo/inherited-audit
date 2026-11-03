"""Checkout: turns a cart into a paid order, using catalog stock, the order book and the card gateway."""
from payments.money import to_cents


class Checkout:
    def __init__(self, orders, inventory, payments, prices, attempts=None):
        self._orders = orders
        self._inventory = inventory
        self._payments = payments
        self._prices = prices
        self._attempts = attempts if attempts is not None else []

    def submit(self, owner, items, card_token):
        """Reserve the stock, place the order and charge the card for it. Returns the paid order."""
        for item in items:
            self._inventory.reserve(item["sku"], item["qty"])
        order = self._orders.place(owner, items)
        total = self._orders.total_cents(order["number"], self._prices)
        charge = self._payments.charge(order["number"], to_cents(total), card_token)
        return self._orders.mark_paid(order["number"], charge["id"])

    def pay_again(self, number, card_token):
        """Charge an order whose first payment did not go through. Every attempt is written to the attempt log,
        and a gateway error reaches the caller, who decides whether to tell the buyer."""
        paid = None
        try:
            total = self._orders.total_cents(number, self._prices)
            charge = self._payments.charge(number, total, card_token)
            paid = self._orders.mark_paid(number, charge["id"])
        finally:
            self._attempts.append((number, "paid" if paid else "failed"))
            return paid

    def attempts_for(self, number):
        return [outcome for n, outcome in self._attempts if n == number]

    def cart_total_cents(self, items):
        return sum(self._prices[item["sku"]] * item["qty"] for item in items)

    def describe(self, order):
        count = sum(item["qty"] for item in order["items"])
        return f"order {order['number']}: {count} units, {order['status']}"

    def can_fulfil(self, items):
        return all(self._inventory.available(item["sku"]) >= item["qty"] for item in items)

    def missing_skus(self, items):
        return sorted(item["sku"] for item in items if item["sku"] not in self._prices)

    def cancel(self, number):
        """Cancel a placed order that was never paid, and give its stock back."""
        order = self._orders.cancel(number)
        for item in order["items"]:
            self._inventory.release(item["sku"], item["qty"])
        return order
