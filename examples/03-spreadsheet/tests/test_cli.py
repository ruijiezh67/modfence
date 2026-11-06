import unittest

from sheet.cli.repl import execute, render
from sheet.engine.sheet import Sheet


class ReplTests(unittest.TestCase):
    def setUp(self):
        self.sheet = Sheet()

    def test_set_and_get(self):
        execute(self.sheet, "set A1 2")
        execute(self.sheet, "set B1 =A1*3")
        self.assertEqual(execute(self.sheet, "get B1"), "6")
        self.assertEqual(execute(self.sheet, "get C1"), "(empty)")

    def test_formula_with_spaces(self):
        execute(self.sheet, "set A1 =1 + 2")
        self.assertEqual(execute(self.sheet, "get A1"), "3")

    def test_show(self):
        self.assertEqual(execute(self.sheet, "show"), "(empty sheet)")
        execute(self.sheet, "set A1 1")
        execute(self.sheet, "set B2 =A1/0")
        lines = render(self.sheet).splitlines()
        self.assertEqual(len(lines), 3)
        self.assertTrue(lines[2].endswith("#DIV/0!"))

    def test_errors_are_reported_not_raised(self):
        self.assertTrue(execute(self.sheet, "set A0 1").startswith("error:"))
        self.assertTrue(execute(self.sheet, "set A1 hello").startswith("error:"))

    def test_quit_and_help(self):
        self.assertIsNone(execute(self.sheet, "quit"))
        self.assertTrue(execute(self.sheet, "bogus").startswith("commands:"))


if __name__ == "__main__":
    unittest.main()
