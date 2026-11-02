import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.environ["BENCH_REPO"], "src"))

from payments.client import PaymentsClient


class Proof(unittest.TestCase):
    def test_jitter_only_spreads_retry_delays(self):
        client = PaymentsClient(transport=None)
        for attempt in range(3):
            delay = client._backoff(attempt)
            self.assertTrue((2 ** attempt) * 0.1 <= delay <= (2 ** attempt) * 0.1 + 0.1)


if __name__ == "__main__":
    unittest.main()
