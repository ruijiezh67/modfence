import contextlib
import io
import unittest

from calc.cli.repl import calculate, format_number, main


class CliTests(unittest.TestCase):
    def test_calculate(self):
        self.assertEqual(calculate("1 + 2*3"), "7")
        self.assertEqual(calculate("6 / 4"), "1.5")

    def test_format_number(self):
        self.assertEqual(format_number(3.0), "3")
        self.assertEqual(format_number(0.1 + 0.2), "0.3")

    def test_one_shot(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main(["1", "+", "2"])
        self.assertEqual((code, out.getvalue().strip()), (0, "3"))

    def test_error_exit_code(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = main(["1 / 0"])
        self.assertEqual(code, 1)
        self.assertIn("division by zero", err.getvalue())


if __name__ == "__main__":
    unittest.main()
