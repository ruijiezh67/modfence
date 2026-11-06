import unittest

from calc.lexer.scanner import LexError, tokenize
from calc.lexer.tokens import Kind


class TokenizeTests(unittest.TestCase):
    def test_kinds(self):
        kinds = [t.kind for t in tokenize("1 + 2.5")]
        self.assertEqual(kinds, [Kind.NUMBER, Kind.PLUS, Kind.NUMBER, Kind.END])

    def test_positions(self):
        self.assertEqual([t.pos for t in tokenize("1 +2")], [0, 2, 3, 4])

    def test_unknown_character(self):
        with self.assertRaises(LexError):
            tokenize("1 ^ 2")

    def test_malformed_number(self):
        with self.assertRaises(LexError):
            tokenize("1.2.3")


if __name__ == "__main__":
    unittest.main()
