"""Background worker that turns queued events into emails."""
import logging

log = logging.getLogger(__name__)


class Worker:
    def __init__(self, queue, mailer):
        self._queue = queue
        self._mailer = mailer

    def run_once(self):
        """Process one message, if any. Returns True when a message was handled."""
        message = self._queue.receive()
        if message is None:
            return False
        self._queue.ack(message["id"])
        self._handle(message)
        return True

    def drain(self, max_messages=100):
        handled = 0
        while handled < max_messages and self.run_once():
            handled += 1
        return handled

    def subject_for(self, template):
        subjects = {"welcome": "Welcome to the shop", "shipped": "Your order is on its way"}
        return subjects.get(template, "News from the shop")

    def pending_hint(self):
        size = getattr(self._queue, "size", None)
        return size() if callable(size) else None

    def describe(self, message):
        return f"{message['template']} email to {message['to']}"

    def _handle(self, message):
        try:
            self._mailer.send(message["to"], self.subject_for(message["template"]), message.get("data", {}))
        except Exception:
            log.exception("could not send message %s", message["id"])
            raise
