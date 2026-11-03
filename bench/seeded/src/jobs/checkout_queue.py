"""Consumer for the checkout requests that the storefront puts on the queue.

The queue delivers every message at least once: a message whose ack does not arrive in time is delivered again.
Each request carries the storefront's `request_id`."""


class CheckoutConsumer:
    def __init__(self, queue, checkout):
        self._queue = queue
        self._checkout = checkout

    def run_once(self):
        """Handle one checkout request, if any, and ack it once handled. Returns True when one was handled."""
        message = self._queue.receive()
        if message is None:
            return False
        self._checkout.submit(message["owner"], message["items"], message["card"])
        self._queue.ack(message["id"])
        return True
