"""Product records as plain dicts, and what the product page shows about them."""


def make_product(sku, name, price_cents, discount_pct=0):
    return {"sku": sku, "name": name, "price_cents": price_cents, "discount_pct": discount_pct}


def final_price_cents(product):
    discount = product.get("discount_pct", 0)
    return product["price_cents"] * (100 - discount) // 100


def label_set(product, labels=[]):
    """Labels for the product page: the given ones, plus "sale" when the product is discounted."""
    if product.get("discount_pct"):
        labels.append("sale")
    return labels
