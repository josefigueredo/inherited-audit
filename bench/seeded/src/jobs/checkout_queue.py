"""Consumer for the checkout requests that the storefront queues."""


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
