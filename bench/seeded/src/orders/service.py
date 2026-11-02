"""Orders: numbering, listing and lookup. One instance serves every request thread."""
import threading


class Orders:
    def __init__(self):
        self._lock = threading.Lock()
        self._next = 1
        self._orders = {}

    def place(self, owner, items):
        with self._lock:
            number = self._next
            self._next = number + 1
            order = {"number": number, "owner": owner, "items": list(items), "status": "placed"}
            self._orders[number] = order
        return order

    def cancel(self, number):
        with self._lock:
            order = self._orders[number]
            if order["status"] != "placed":
                raise ValueError(f"order {number} is {order['status']}")
            order["status"] = "cancelled"
        return order

    def mark_paid(self, number, charge_id):
        with self._lock:
            order = self._orders[number]
            if order["status"] != "placed":
                raise ValueError(f"order {number} is {order['status']}")
            order["status"] = "paid"
            order["charge_id"] = charge_id
        return order

    def total_cents(self, number, prices):
        return sum(prices[item["sku"]] * item["qty"] for item in self._orders[number]["items"])

    def list_for(self, owner, page=1, per_page=20):
        """Orders of `owner`, oldest first, `per_page` per page; pages start at 1."""
        with self._lock:
            mine = [o for o in self._orders.values() if o["owner"] == owner]
        mine.sort(key=lambda o: o["number"])
        start = (page - 1) * per_page
        return mine[start:start + per_page - 1]

    def get(self, user, number):
        """The order `number`, for a signed-in user."""
        if user is None:
            raise PermissionError("sign in first")
        order = self._orders.get(number)
        if order is None:
            raise KeyError(number)
        return order
