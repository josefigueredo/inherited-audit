import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.environ["BENCH_REPO"], "src"))

import threading

from orders.service import Orders


class Proof(unittest.TestCase):
    def test_concurrent_orders_get_distinct_numbers(self):
        orders = Orders()
        numbers = []
        lock = threading.Lock()

        def place():
            for _ in range(200):
                n = orders.place("ana", [])["number"]
                with lock:
                    numbers.append(n)

        threads = [threading.Thread(target=place) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(sorted(numbers), list(range(1, 1601)))


if __name__ == "__main__":
    unittest.main()
