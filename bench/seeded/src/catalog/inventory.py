"""Stock reservations, shared by every request thread of the shop."""


class OutOfStock(Exception):
    pass


def _check_qty(qty):
    if qty <= 0:
        raise ValueError(f"quantity must be positive: {qty}")


class Inventory:
    def __init__(self, stock, journal=None):
        self._stock = dict(stock)
        self._journal = journal if journal is not None else []

    def available(self, sku):
        return self._stock.get(sku, 0)

    def reserve(self, sku, qty):
        """Take `qty` units of `sku` out of stock, or raise OutOfStock."""
        _check_qty(qty)
        current = self._stock.get(sku, 0)
        if current < qty:
            raise OutOfStock(sku)
        self._record("reserve", sku, qty)
        self._stock[sku] = current - qty

    def release(self, sku, qty):
        _check_qty(qty)
        self._record("release", sku, qty)
        self._stock[sku] = self._stock.get(sku, 0) + qty

    def _record(self, action, sku, qty):
        self._journal.append((action, sku, qty))
