"""CSV import and export. Row 1 of the file is row 1 of the sheet."""

import csv
from typing import TextIO

from sheet.cells.address import CellAddress
from sheet.engine.sheet import Sheet
from sheet.engine.values import format_value


def export_csv(sheet: Sheet, stream: TextIO, values: bool = False) -> None:
    """Write the sheet as CSV: formulas as entered, or computed values if ``values``."""
    max_row, max_col = sheet.bounds()
    writer = csv.writer(stream, lineterminator="\n")
    for row in range(1, max_row + 1):
        fields = []
        for col in range(1, max_col + 1):
            label = CellAddress(row, col).label
            fields.append(format_value(sheet.value(label)) if values else sheet.raw(label))
        writer.writerow(fields)


def import_csv(sheet: Sheet, stream: TextIO) -> int:
    """Load CSV into the sheet and return the number of cells set."""
    count = 0
    for row, fields in enumerate(csv.reader(stream), start=1):
        for col, field in enumerate(fields, start=1):
            if field.strip():
                sheet.set(CellAddress(row, col).label, field)
                count += 1
    return count
