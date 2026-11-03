"""Storefront handlers: each one turns a buyer's request into a status code and a body."""
import uuid

from payments.client import GatewayTimeout


def enqueue_checkout(queue, owner, items, card_token):
    """Queue a checkout for the consumer; the buyer gets an answer at once."""
    queue.put({"request_id": str(uuid.uuid4()), "owner": owner, "items": items, "card": card_token})
    return {"status": 202}


def retry_payment(checkout, number, card_token):
    """The buyer asks to pay an order again. When the gateway does not answer, they are told to try later."""
    try:
        order = checkout.pay_again(number, card_token)
    except GatewayTimeout:
        return {"status": 503, "message": "The card gateway did not answer. Try again in a minute."}
    return {"status": 200, "order": order["number"], "state": order["status"]}
