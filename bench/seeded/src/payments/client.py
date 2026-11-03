"""Client for the card gateway. The transport does the HTTP; this class decides what to send and when to retry."""
import random
import time


class GatewayTimeout(Exception):
    pass


class PaymentsClient:
    def __init__(self, transport, retries=3, sleep=time.sleep):
        self._transport = transport
        self._retries = retries
        self._sleep = sleep

    def charge(self, order_number, amount_cents, card_token):
        """Charge the card once for the order; returns the gateway's charge."""
        payload = {"order": order_number, "amount": amount_cents, "card": card_token}
        for attempt in range(self._retries):
            try:
                return self._transport.post("/charges", payload)
            except GatewayTimeout:
                if attempt + 1 < self._retries:
                    self._sleep(self._backoff(attempt))
        raise GatewayTimeout(f"charge for order {order_number}")

    def refund(self, charge_id, amount_cents):
        """Refund part or all of a charge. Not retried: the caller decides after a timeout."""
        return self._transport.post(f"/charges/{charge_id}/refunds", {"amount": amount_cents})

    def receipt_url(self, charge_id):
        return f"/charges/{charge_id}/receipt"

    def describe(self, charge):
        status = charge.get("status", "unknown")
        return f"charge {charge.get('id')} for {charge.get('amount')} cents is {status}"

    def amount_of(self, charge):
        return charge.get("amount", 0)

    def is_settled(self, charge):
        return charge.get("status") in ("succeeded", "refunded")

    def charge_status(self, charge_id):
        """Current status of a charge; reading it twice changes nothing."""
        for attempt in range(self._retries):
            try:
                return self._transport.get(f"/charges/{charge_id}")
            except GatewayTimeout:
                if attempt + 1 < self._retries:
                    self._sleep(self._backoff(attempt))
        raise GatewayTimeout(f"status of charge {charge_id}")

    def _backoff(self, attempt):
        return (2 ** attempt) * 0.1 + random.uniform(0, 0.1)
