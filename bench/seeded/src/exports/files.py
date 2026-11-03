"""Exported files and reports, all kept under one folder."""
import os


class Exports:
    def __init__(self, base_dir):
        self._base = os.path.realpath(base_dir)

    def read_export(self, name):
        """Content of an export file, by name."""
        with open(os.path.join(self._base, name), encoding="utf-8") as fh:
            return fh.read()

    def write_export(self, name, content):
        if os.path.basename(name) != name or name in ("", ".", ".."):
            raise ValueError(f"bad export name: {name!r}")
        with open(os.path.join(self._base, name), "w", encoding="utf-8") as fh:
            fh.write(content)

    def list_exports(self):
        return sorted(n for n in os.listdir(self._base) if os.path.isfile(os.path.join(self._base, n)))

    def size(self, name):
        return os.path.getsize(os.path.join(self._base, os.path.basename(name)))

    def remove_export(self, name):
        if os.path.basename(name) != name or name in ("", ".", ".."):
            raise ValueError(f"bad export name: {name!r}")
        os.remove(os.path.join(self._base, name))

    def total_size(self):
        total = 0
        for name in self.list_exports():
            try:
                total += self.size(name)
            except FileNotFoundError:
                continue  # removed after the listing
        return total

    def read_report(self, name):
        """Content of a report under <base>/reports; names that leave that folder are refused."""
        folder = os.path.realpath(os.path.join(self._base, "reports"))
        path = os.path.realpath(os.path.join(folder, name))
        if os.path.commonpath([path, folder]) != folder:
            raise ValueError(f"bad report name: {name!r}")
        with open(path, encoding="utf-8") as fh:
            return fh.read()
