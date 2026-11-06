import io
import unittest

from sheet.engine.sheet import Sheet
from sheet.io.csv_io import export_csv, import_csv

CSV_TEXT = "1,2,=A1+B1\n,,=SUM(A1:C1)\n"


class CsvTests(unittest.TestCase):
    def test_import(self):
        sheet = Sheet()
        count = import_csv(sheet, io.StringIO(CSV_TEXT))
        self.assertEqual(count, 4)
        self.assertEqual(sheet.value("C1"), 3)
        self.assertEqual(sheet.value("C2"), 6)

    def test_export_formulas_round_trip(self):
        sheet = Sheet()
        import_csv(sheet, io.StringIO(CSV_TEXT))
        out = io.StringIO()
        export_csv(sheet, out)
        self.assertEqual(out.getvalue(), CSV_TEXT)

    def test_export_values(self):
        sheet = Sheet()
        import_csv(sheet, io.StringIO(CSV_TEXT))
        out = io.StringIO()
        export_csv(sheet, out, values=True)
        self.assertEqual(out.getvalue(), "1,2,3\n,,6\n")

    def test_export_empty_sheet(self):
        out = io.StringIO()
        export_csv(Sheet(), out)
        self.assertEqual(out.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
