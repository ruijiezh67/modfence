import unittest

from sheet.cells.address import (
    CellAddress,
    InvalidAddress,
    column_index,
    column_letters,
    parse_address,
)
from sheet.cells.ranges import parse_range


class AddressTests(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(parse_address("A1"), CellAddress(1, 1))
        self.assertEqual(parse_address("b3"), CellAddress(3, 2))
        self.assertEqual(parse_address("AA10"), CellAddress(10, 27))

    def test_label_round_trip(self):
        for label in ["A1", "Z9", "AA1", "ZZ9999"]:
            self.assertEqual(parse_address(label).label, label)

    def test_columns(self):
        self.assertEqual(column_letters(26), "Z")
        self.assertEqual(column_letters(27), "AA")
        self.assertEqual(column_index("AB"), 28)

    def test_invalid(self):
        for bad in ["", "A", "1A", "A0", "AAA1", "A10000", "A1B"]:
            with self.subTest(text=bad):
                with self.assertRaises(InvalidAddress):
                    parse_address(bad)


class RangeTests(unittest.TestCase):
    def test_addresses_row_major(self):
        labels = [a.label for a in parse_range("A1:B2").addresses()]
        self.assertEqual(labels, ["A1", "B1", "A2", "B2"])

    def test_normalizes_corners(self):
        self.assertEqual(parse_range("B2:A1").label, "A1:B2")

    def test_not_a_range(self):
        with self.assertRaises(InvalidAddress):
            parse_range("A1")


if __name__ == "__main__":
    unittest.main()
