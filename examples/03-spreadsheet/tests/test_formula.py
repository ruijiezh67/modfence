import unittest

from sheet.cells.address import InvalidAddress, parse_address
from sheet.formula.analysis import dependencies
from sheet.formula.lexer import FormulaError, Kind, tokenize
from sheet.formula.nodes import BinOp, Call, Neg, Number, RangeRef, Ref
from sheet.formula.parser import parse_formula


class LexerTests(unittest.TestCase):
    def test_kinds(self):
        kinds = [t.kind for t in tokenize("SUM(A1:A3, 2)")]
        self.assertEqual(
            kinds,
            [Kind.NAME, Kind.LPAREN, Kind.NAME, Kind.COLON, Kind.NAME, Kind.COMMA,
             Kind.NUMBER, Kind.RPAREN, Kind.END],
        )

    def test_bad_character(self):
        with self.assertRaises(FormulaError):
            tokenize("1 $ 2")


class ParserTests(unittest.TestCase):
    def test_precedence(self):
        a1, b2 = parse_address("A1"), parse_address("B2")
        node = parse_formula("=A1+B2*2")
        self.assertEqual(node, BinOp("+", Ref(a1), BinOp("*", Ref(b2), Number(2.0))))

    def test_function_and_range(self):
        node = parse_formula("=sum(A1:A3)")
        self.assertIsInstance(node, Call)
        self.assertEqual(node.name, "SUM")
        self.assertIsInstance(node.args[0], RangeRef)

    def test_unary_and_parens(self):
        self.assertIsInstance(parse_formula("=-(1+2)"), Neg)

    def test_syntax_errors(self):
        for bad in ["=", "=1+", "=(1", "=SUM(1,)", "=FOO", "=A1:5", "=1 2"]:
            with self.subTest(formula=bad):
                with self.assertRaises(FormulaError):
                    parse_formula(bad)

    def test_out_of_bounds_reference(self):
        with self.assertRaises(InvalidAddress):
            parse_formula("=A10000")


class AnalysisTests(unittest.TestCase):
    def test_dependencies_expand_ranges(self):
        labels = {a.label for a in dependencies(parse_formula("=SUM(A1:A3)+B1"))}
        self.assertEqual(labels, {"A1", "A2", "A3", "B1"})

    def test_constants_have_none(self):
        self.assertEqual(dependencies(parse_formula("=1+2")), set())


if __name__ == "__main__":
    unittest.main()
