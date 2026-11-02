import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.environ["BENCH_REPO"], "src"))

from jobs.worker import Worker


class Proof(unittest.TestCase):
    def test_a_send_error_reaches_the_caller(self):
        class Mailer:
            def send(self, to, subject, data):
                raise ConnectionError("smtp down")

        with self.assertLogs("jobs.worker", level="ERROR"):
            with self.assertRaises(ConnectionError):
                Worker(queue=None, mailer=Mailer())._handle({"id": "m1", "to": "a@example.com", "template": "x"})


if __name__ == "__main__":
    unittest.main()
