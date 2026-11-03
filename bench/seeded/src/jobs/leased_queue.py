"""In-process queue with leases: the same contract as the hosted queue the shop uses in production."""
import itertools
import time


class LeasedQueue:
    def __init__(self, lease_seconds=30, clock=time.monotonic):
        self._lease_seconds = lease_seconds
        self._clock = clock
        self._ready = []
        self._leased = {}
        self._ids = itertools.count(1)

    def put(self, body):
        self._ready.append({**body, "id": f"m{next(self._ids)}"})

    def receive(self):
        """The next message, leased to the caller for lease_seconds. Expired leases go back to the queue first."""
        now = self._clock()
        for message_id, (message, until) in list(self._leased.items()):
            if until <= now:
                del self._leased[message_id]
                self._ready.append(message)
        if not self._ready:
            return None
        message = self._ready.pop(0)
        self._leased[message["id"]] = (message, now + self._lease_seconds)
        return message

    def ack(self, message_id):
        """Remove a message whose lease is still running. Returns whether it was removed."""
        entry = self._leased.get(message_id)
        if entry is None or entry[1] <= self._clock():
            return False
        del self._leased[message_id]
        return True

    def size(self):
        return len(self._ready) + len(self._leased)
