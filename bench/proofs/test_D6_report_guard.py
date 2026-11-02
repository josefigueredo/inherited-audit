import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.environ["BENCH_REPO"], "src"))

import tempfile

from exports.files import Exports


class Proof(unittest.TestCase):
    def test_report_names_cannot_leave_reports(self):
        with tempfile.TemporaryDirectory() as root:
            os.makedirs(os.path.join(root, "reports"))
            with open(os.path.join(root, "private.txt"), "w", encoding="utf-8") as fh:
                fh.write("private")
            exports = Exports(root)
            for name in ("../private.txt", "/etc/hosts", "reports/../../private.txt"):
                with self.assertRaises(ValueError, msg=name):
                    exports.read_report(name)


if __name__ == "__main__":
    unittest.main()
