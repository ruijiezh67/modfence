"""A small line-based REPL.

Commands: ``set CELL TEXT``, ``get CELL``, ``show``, ``import FILE``,
``export FILE [values]``, ``help``, ``quit``.
"""

from sheet.cells.address import CellAddress, InvalidAddress, column_letters
from sheet.engine.sheet import Sheet, SheetError
from sheet.engine.values import format_value
from sheet.io.csv_io import export_csv, import_csv

HELP = "commands: set CELL TEXT | get CELL | show | import FILE | export FILE [values] | quit"


def render(sheet: Sheet) -> str:
    """The sheet's computed values as a text table."""
    max_row, max_col = sheet.bounds()
    if max_row == 0:
        return "(empty sheet)"
    header = " " * 5 + "".join(column_letters(c).rjust(10) for c in range(1, max_col + 1))
    lines = [header]
    for row in range(1, max_row + 1):
        cells = (
            format_value(sheet.value(CellAddress(row, col).label)).rjust(10)
            for col in range(1, max_col + 1)
        )
        lines.append(f"{row:>4} " + "".join(cells))
    return "\n".join(lines)


def execute(sheet: Sheet, line: str) -> str | None:
    """Run one command and return its output; None means quit."""
    parts = line.split(None, 2)
    if not parts:
        return ""
    command, args = parts[0].lower(), parts[1:]
    try:
        if command in ("quit", "exit"):
            return None
        if command == "set" and len(args) >= 1:
            sheet.set(args[0], args[1] if len(args) > 1 else "")
            return ""
        if command == "get" and len(args) == 1:
            return format_value(sheet.value(args[0])) or "(empty)"
        if command == "show":
            return render(sheet)
        if command == "import" and len(args) == 1:
            with open(args[0], newline="", encoding="utf-8") as handle:
                return f"imported {import_csv(sheet, handle)} cells"
        if command == "export" and len(args) >= 1:
            as_values = len(args) > 1 and args[1].strip() == "values"
            with open(args[0], "w", newline="", encoding="utf-8") as handle:
                export_csv(sheet, handle, values=as_values)
            return f"exported to {args[0]}"
        return HELP
    except (InvalidAddress, SheetError, OSError) as exc:
        return f"error: {exc}"


def main(argv: list[str] | None = None) -> int:
    """Read commands from standard input until ``quit`` or end of input."""
    sheet = Sheet()
    while True:
        try:
            line = input("sheet> ")
        except EOFError:
            return 0
        output = execute(sheet, line)
        if output is None:
            return 0
        if output:
            print(output)
