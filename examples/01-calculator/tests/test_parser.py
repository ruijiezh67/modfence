import unittest

from calc.parser.nodes import BinOp, Num, UnaryOp
from calc.parser.parser import ParseError, parse


class ParserTests(unittest.TestCase):
    def test_precedence(self):
        tree = parse("1 + 2 * 3")
        self.assertEqual(tree, BinOp("+", Num(1), BinOp("*", Num(2), Num(3))))

    def test_left_associative(self):
        tree = parse("8 - 3 - 2")
        self.assertEqual(tree, BinOp("-", BinOp("-", Num(8), Num(3)), Num(2)))

    def test_parentheses(self):
        tree = parse("(1 + 2) * 3")
        self.assertEqual(tree, BinOp("*", BinOp("+", Num(1), Num(2)), Num(3)))

    def test_unary_minus(self):
        self.assertEqual(parse("--4"), UnaryOp("-", UnaryOp("-", Num(4))))

    def test_decimal(self):
        self.assertEqual(parse("1.5"), Num(1.5))

    def test_errors(self):
        for bad in ["", "1 +", "(1 + 2", "1 2", ")"]:
            with self.subTest(source=bad):
                with self.assertRaises(ParseError):
                    parse(bad)


if __name__ == "__main__":
    unittest.main()
