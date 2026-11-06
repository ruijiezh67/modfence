import unittest

from calc.evaluator.evaluate import EvalError, evaluate
from calc.parser.parser import parse


class EvaluateTests(unittest.TestCase):
    def check(self, source, expected):
        self.assertAlmostEqual(evaluate(parse(source)), expected)

    def test_arithmetic(self):
        self.check("1 + 2 * 3", 7)
        self.check("(1 + 2) * 3", 9)
        self.check("10 / 4", 2.5)
        self.check("-(2 + 3)", -5)
        self.check("2 * -3", -6)

    def test_decimals(self):
        self.check("0.5 + 0.25", 0.75)

    def test_division_by_zero(self):
        with self.assertRaises(EvalError):
            evaluate(parse("1 / (2 - 2)"))


if __name__ == "__main__":
    unittest.main()
