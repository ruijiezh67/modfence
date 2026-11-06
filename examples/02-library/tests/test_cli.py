import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from library.cli.app import main


class CliTests(unittest.TestCase):
    def call(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(list(argv))
        return code, out.getvalue().strip(), err.getvalue().strip()

    def test_full_session(self):
        with tempfile.TemporaryDirectory() as folder:
            data = str(Path(folder) / "lib.json")
            base = ["--data", data, "--today", "2026-03-01"]
            self.assertEqual(self.call(*base, "add-book", "b1", "Dune", "Herbert")[0], 0)
            self.assertEqual(self.call(*base, "add-member", "m1", "Ada")[0], 0)
            code, out, _ = self.call(*base, "lend", "b1", "m1")
            self.assertEqual((code, out), (0, "loan 1: due 2026-03-15"))
            late = ["--data", data, "--today", "2026-03-20"]
            code, out, _ = self.call(*late, "overdue")
            self.assertEqual(out, "loan 1 b1 m1 5 days")
            self.assertEqual(self.call(*late, "return", "1")[1], "loan 1 returned")
            self.assertEqual(self.call(*late, "popular")[1], "1 x Dune")

    def test_error_exit_code(self):
        with tempfile.TemporaryDirectory() as folder:
            data = str(Path(folder) / "lib.json")
            code, _, err = self.call("--data", data, "lend", "x", "y")
            self.assertEqual(code, 1)
            self.assertIn("error:", err)


if __name__ == "__main__":
    unittest.main()
