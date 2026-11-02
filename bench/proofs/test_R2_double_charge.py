import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.environ["BENCH_REPO"], "src"))

from payments.client import GatewayTimeout, PaymentsClient


class Proof(unittest.TestCase):
    def test_a_retried_charge_cannot_be_charged_twice(self):
        posts = []

        class Transport:
            def post(self, path, payload):
                posts.append(dict(payload))
                if len(posts) == 1:
                    raise GatewayTimeout("the gateway charged the card but the answer was lost")
                return {"id": "ch_1"}

        PaymentsClient(Transport(), sleep=lambda s: None).charge(7, 2500, "tok_1")
        keys = {p.get("idempotency_key") for p in posts}
        self.assertTrue(len(posts) == 1 or (len(keys) == 1 and None not in keys),
                        f"{len(posts)} charge requests without a shared idempotency key")


if __name__ == "__main__":
    unittest.main()
