import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.environ["BENCH_REPO"], "src"))

from jobs.worker import Worker


class Proof(unittest.TestCase):
    def test_a_message_that_fails_is_not_acknowledged(self):
        acked = []

        class Queue:
            def receive(self):
                return {"id": "m1", "to": "ana@example.com", "template": "welcome"}

            def ack(self, message_id):
                acked.append(message_id)

        class Mailer:
            def send(self, to, subject, data):
                raise ConnectionError("smtp down")

        with self.assertRaises(ConnectionError):
            Worker(Queue(), Mailer()).run_once()
        self.assertEqual(acked, [])


if __name__ == "__main__":
    unittest.main()
