import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.environ["BENCH_REPO"], "src"))

from payments.money import to_cents


class Proof(unittest.TestCase):
    def test_rounds_half_up_as_documented(self):
        self.assertEqual(to_cents("0.125"), 13)
        self.assertEqual(to_cents("1.005"), 101)


if __name__ == "__main__":
    unittest.main()
