import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.environ["BENCH_REPO"], "src"))

import threading

from catalog.inventory import Inventory, OutOfStock


class Proof(unittest.TestCase):
    def test_two_buyers_cannot_both_take_the_last_unit(self):
        inv = Inventory({"A": 1})
        barrier = threading.Barrier(2, timeout=2)
        original = inv._record

        def slow_record(action, sku, qty):
            try:
                barrier.wait()
            except threading.BrokenBarrierError:
                pass
            original(action, sku, qty)

        inv._record = slow_record
        wins = []

        def buy():
            try:
                inv.reserve("A", 1)
                wins.append(1)
            except OutOfStock:
                pass

        threads = [threading.Thread(target=buy) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(5)
        self.assertEqual(len(wins), 1)


if __name__ == "__main__":
    unittest.main()
