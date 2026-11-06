import unittest

from sheet.cells.address import InvalidAddress
from sheet.engine.sheet import Sheet, SheetError
from sheet.engine.values import CellError, format_value


class SheetTests(unittest.TestCase):
    def setUp(self):
        self.sheet = Sheet()

    def test_numbers_and_formulas(self):
        self.sheet.set("A1", "2")
        self.sheet.set("B2", "5")
        self.sheet.set("C1", "=A1+B2*2")
        self.assertEqual(self.sheet.value("C1"), 12)

    def test_functions_over_ranges(self):
        for i, v in enumerate(["1", "2", "3"], start=1):
            self.sheet.set(f"A{i}", v)
        self.sheet.set("B1", "=SUM(A1:A3)")
        self.sheet.set("B2", "=AVG(A1:A3)")
        self.sheet.set("B3", "=MAX(A1:A3, 10)")
        self.assertEqual([self.sheet.value(f"B{i}") for i in (1, 2, 3)], [6, 2, 10])

    def test_empty_cells_in_ranges_are_skipped(self):
        self.sheet.set("A1", "4")
        self.sheet.set("B1", "=AVG(A1:A3)")
        self.assertEqual(self.sheet.value("B1"), 4)

    def test_dependents_update(self):
        self.sheet.set("A1", "1")
        self.sheet.set("B1", "=A1*10")
        self.sheet.set("C1", "=B1+1")
        self.sheet.set("A1", "2")
        self.assertEqual(self.sheet.value("C1"), 21)

    def test_recalculation_is_incremental(self):
        self.sheet.set("A1", "1")
        self.sheet.set("B1", "=A1+1")
        self.sheet.set("Z9", "7")
        self.sheet.set("A1", "5")
        self.assertEqual({a.label for a in self.sheet.last_recalculated}, {"A1", "B1"})

    def test_formulas_can_be_set_before_their_inputs(self):
        self.sheet.set("B1", "=A1+1")
        self.assertEqual(self.sheet.value("B1"), 1)
        self.sheet.set("A1", "9")
        self.assertEqual(self.sheet.value("B1"), 10)

    def test_clear_cell(self):
        self.sheet.set("A1", "3")
        self.sheet.set("B1", "=A1")
        self.sheet.set("A1", "")
        self.assertIsNone(self.sheet.value("A1"))
        self.assertEqual(self.sheet.value("B1"), 0)

    def test_div_zero_propagates(self):
        self.sheet.set("A1", "0")
        self.sheet.set("B1", "=1/A1")
        self.sheet.set("C1", "=B1+1")
        self.assertEqual(self.sheet.value("B1"), CellError.DIV0)
        self.assertEqual(self.sheet.value("C1"), CellError.DIV0)
        self.sheet.set("A1", "4")
        self.assertEqual(self.sheet.value("C1"), 1.25)

    def test_avg_of_nothing_is_div_zero(self):
        self.sheet.set("A1", "=AVG(B1:B3)")
        self.assertEqual(self.sheet.value("A1"), CellError.DIV0)

    def test_cycle(self):
        self.sheet.set("A1", "=B1")
        self.sheet.set("B1", "=A1")
        self.sheet.set("C1", "=A1+1")
        self.assertEqual(self.sheet.value("A1"), CellError.CYCLE)
        self.assertEqual(self.sheet.value("B1"), CellError.CYCLE)
        self.assertEqual(self.sheet.value("C1"), CellError.CYCLE)

    def test_self_reference_and_recovery(self):
        self.sheet.set("A1", "=A1+1")
        self.assertEqual(self.sheet.value("A1"), CellError.CYCLE)
        self.sheet.set("A1", "5")
        self.assertEqual(self.sheet.value("A1"), 5)

    def test_cycle_broken_by_editing(self):
        self.sheet.set("A1", "=B1")
        self.sheet.set("B1", "=A1")
        self.sheet.set("B1", "3")
        self.assertEqual(self.sheet.value("A1"), 3)

    def test_ref_error(self):
        self.sheet.set("A1", "=B10000")
        self.assertEqual(self.sheet.value("A1"), CellError.REF)

    def test_other_errors(self):
        self.sheet.set("A1", "=FOO(1)")
        self.sheet.set("A2", "=1+")
        self.assertEqual(self.sheet.value("A1"), CellError.NAME)
        self.assertEqual(self.sheet.value("A2"), CellError.SYNTAX)

    def test_unsupported_content(self):
        with self.assertRaises(SheetError):
            self.sheet.set("A1", "hello")
        with self.assertRaises(InvalidAddress):
            self.sheet.set("A0", "1")

    def test_format_value(self):
        self.assertEqual(format_value(3.0), "3")
        self.assertEqual(format_value(2.5), "2.5")
        self.assertEqual(format_value(CellError.REF), "#REF!")
        self.assertEqual(format_value(None), "")


if __name__ == "__main__":
    unittest.main()
