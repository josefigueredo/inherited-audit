import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.environ["BENCH_REPO"], "src"))

from payments.client import GatewayTimeout, PaymentsClient


class Proof(unittest.TestCase):
    def test_status_retries_only_read(self):
        calls = []

        class Transport:
            def get(self, path):
                calls.append(("GET", path))
                if len(calls) == 1:
                    raise GatewayTimeout("slow")
                return {"id": "ch_1", "status": "succeeded"}

            def post(self, path, payload):
                calls.append(("POST", path))

        status = PaymentsClient(Transport(), sleep=lambda s: None).charge_status("ch_1")
        self.assertEqual(status["status"], "succeeded")
        self.assertEqual({method for method, _ in calls}, {"GET"})


if __name__ == "__main__":
    unittest.main()
