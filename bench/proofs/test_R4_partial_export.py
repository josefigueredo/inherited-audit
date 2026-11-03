import builtins
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.environ["BENCH_REPO"], "src"))

import exports.files as files
from exports.files import Exports


class Proof(unittest.TestCase):
    def test_a_reader_during_a_rewrite_sees_the_old_or_the_new_export(self):
        base = tempfile.mkdtemp()
        exports = Exports(base)
        exports.write_export("daily.csv", "id,total\n1,10\n")
        seen = []

        class Spy:
            def __init__(self, fh):
                self.fh = fh

            def __enter__(self):
                self.fh.__enter__()
                return self

            def __exit__(self, *exc):
                return self.fh.__exit__(*exc)

            def write(self, data):
                seen.append(exports.read_export("daily.csv"))  # another reader, in the middle of the write
                return self.fh.write(data)

        def spy_open(path, mode="r", *args, **kwargs):
            fh = builtins.open(path, mode, *args, **kwargs)
            return Spy(fh) if "w" in mode else fh

        files.open = spy_open
        try:
            exports.write_export("daily.csv", "id,total\n1,10\n2,20\n")
        finally:
            del files.open
        self.assertEqual(seen, ["id,total\n1,10\n"])


if __name__ == "__main__":
    unittest.main()
