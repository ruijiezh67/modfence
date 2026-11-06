"""The spreadsheet: stores cells and recalculates only what changed."""

import math

from sheet.cells.address import CellAddress, InvalidAddress, parse_address
from sheet.engine.evaluator import evaluate
from sheet.engine.values import CellError, Value
from sheet.formula.analysis import dependencies
from sheet.formula.lexer import FormulaError
from sheet.formula.nodes import Node
from sheet.formula.parser import parse_formula
from sheet.functions.registry import Registry, default_registry
from sheet.graph.depgraph import CycleError, DependencyGraph


class SheetError(ValueError):
    """Raised when a cell is given content the sheet does not support."""


class Sheet:
    """A grid of numbers and formulas.

    Setting a cell recalculates that cell and the cells that depend on it,
    in dependency order. ``last_recalculated`` lists what was recomputed.
    """

    def __init__(self, registry: Registry | None = None) -> None:
        self._registry = registry or default_registry()
        self._raw: dict[CellAddress, str] = {}
        self._content: dict[CellAddress, float | Node | CellError] = {}
        self._values: dict[CellAddress, Value] = {}
        self._graph: DependencyGraph[CellAddress] = DependencyGraph()
        self.last_recalculated: list[CellAddress] = []

    def set(self, label: str, raw: str) -> None:
        """Set a cell from text: a number, a formula starting with ``=``, or empty to clear."""
        addr = parse_address(label)
        raw = raw.strip()
        if not raw:
            self._raw.pop(addr, None)
            self._content.pop(addr, None)
            self._graph.set_precedents(addr, ())
        elif raw.startswith("="):
            self._raw[addr] = raw
            self._store_formula(addr, raw)
        else:
            self._store_number(addr, raw)
        self._recalculate(addr)

    def _store_number(self, addr: CellAddress, raw: str) -> None:
        try:
            number = float(raw)
        except ValueError:
            raise SheetError(f"only numbers and formulas are supported: {raw!r}") from None
        if not math.isfinite(number):
            raise SheetError(f"not a finite number: {raw!r}")
        self._raw[addr] = raw
        self._content[addr] = number
        self._graph.set_precedents(addr, ())

    def _store_formula(self, addr: CellAddress, raw: str) -> None:
        try:
            node = parse_formula(raw)
        except InvalidAddress:
            self._content[addr] = CellError.REF
            self._graph.set_precedents(addr, ())
        except FormulaError:
            self._content[addr] = CellError.SYNTAX
            self._graph.set_precedents(addr, ())
        else:
            self._content[addr] = node
            self._graph.set_precedents(addr, dependencies(node))

    def _recalculate(self, start: CellAddress) -> None:
        affected = self._graph.descendants(start) | {start}
        try:
            order, cyclic = self._graph.topological_order(affected), set()
        except CycleError as exc:
            order, cyclic = exc.ordered, exc.members
        for addr in cyclic:
            self._values[addr] = CellError.CYCLE
        self.last_recalculated = order
        for addr in order:
            content = self._content.get(addr)
            if content is None:
                self._values.pop(addr, None)
            elif isinstance(content, (float, CellError)):
                self._values[addr] = content
            else:
                self._values[addr] = evaluate(content, self._values.get, self._registry)

    def value(self, label: str) -> Value | None:
        """The computed value of a cell, or None if it is empty."""
        return self._values.get(parse_address(label))

    def raw(self, label: str) -> str:
        """The text the user entered, or an empty string."""
        return self._raw.get(parse_address(label), "")

    def raw_cells(self) -> list[tuple[CellAddress, str]]:
        """All non-empty cells with their entered text, row by row."""
        return sorted(self._raw.items())

    def bounds(self) -> tuple[int, int]:
        """(max row, max column) of non-empty cells, or (0, 0)."""
        if not self._raw:
            return 0, 0
        return max(a.row for a in self._raw), max(a.col for a in self._raw)
