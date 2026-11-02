import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.environ["BENCH_REPO"], "src"))

import tempfile

from exports.files import Exports


class Proof(unittest.TestCase):
    def test_an_export_name_cannot_leave_the_folder(self):
        with tempfile.TemporaryDirectory() as root:
            os.mkdir(os.path.join(root, "exports"))
            with open(os.path.join(root, "private.txt"), "w", encoding="utf-8") as fh:
                fh.write("private")
            exports = Exports(os.path.join(root, "exports"))
            with self.assertRaises((ValueError, PermissionError)):
                exports.read_export("../private.txt")


if __name__ == "__main__":
    unittest.main()
