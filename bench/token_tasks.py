"""Four tasks on rich (github.com/Textualize/rich) for bench/token_bench.py, with their acceptance tests.

How they were made (self-made data, so the rules are written down):
- Source: rich at the commit recorded in each result row (`rich_commit`); 100 files, 26k lines of Python under rich/.
- Each task adds one small public feature to one file-module of rich, the kind of request a user makes by pointing at a
  module. Chosen so that one needs another module's interface (T3 needs rich.text.Text from rich/panel.py) and the
  others need only their own file, which is the common case.
- The spec text is what the agent receives, the same in every arm. The acceptance tests were written from the spec
  before any run and are never shown to the agent; they are copied into the project only after the run.
- What counts as success: all acceptance tests of the task pass, and rich's own test file for that module still passes.
- How it differs from real use: tasks are small and fully specified; a real request is vaguer.
"""

TASKS = {
    "T1-text-count": {
        "module": "rich/text.py",
        "spec": "Add a method `Text.count(substring: str) -> int` to `rich.text.Text` that returns the number of "
                "non-overlapping occurrences of `substring` in the text's plain string, exactly like `str.count` "
                "(an empty substring included).",
        "regression": "tests/test_text.py",
        "accept": '''
from rich.text import Text

def test_counts_like_str_count():
    assert Text("a-b-a").count("a") == 2
    assert Text("aaaa").count("aa") == 2
    assert Text("x").count("") == 2
    assert Text("abc").count("z") == 0

def test_counts_plain_text_not_markup():
    assert Text.from_markup("[b]ab[/b]ab").count("ab") == 2
''',
    },
    "T2-table-add-rows": {
        "module": "rich/table.py",
        "spec": "Add a method `Table.add_rows(rows, *, style=None, end_section=False)` to `rich.table.Table`: add each "
                "row of `rows` (an iterable of iterables of renderables) with `add_row`, passing `style` to every row; "
                "`end_section` applies only to the last row added. It returns None.",
        "regression": "tests/test_table.py",
        "accept": '''
from rich.console import Console
from rich.table import Table

def render(t):
    c = Console(width=40, record=True, color_system=None)
    c.print(t)
    return c.export_text()

def test_same_as_add_row():
    a, b = Table("x", "y"), Table("x", "y")
    a.add_rows([["1", "2"], ["3", "4"]])
    b.add_row("1", "2"); b.add_row("3", "4")
    assert a.row_count == 2 and render(a) == render(b)

def test_style_and_end_section():
    t = Table("x")
    assert t.add_rows(iter([["1"], ["2"], ["3"]]), style="red", end_section=True) is None
    assert [r.style for r in t.rows] == ["red", "red", "red"]
    assert [r.end_section for r in t.rows] == [False, False, True]

def test_empty():
    t = Table("x")
    t.add_rows([])
    assert t.row_count == 0
''',
    },
    "T3-panel-from-markup": {
        "module": "rich/panel.py",
        "spec": "Add a classmethod `Panel.from_markup(markup: str, **kwargs) -> Panel` to `rich.panel.Panel` that "
                "builds the panel's content with `Text.from_markup(markup)` and passes every keyword argument on to "
                "`Panel`.",
        "regression": "tests/test_panel.py",
        "accept": '''
from rich.panel import Panel
from rich.text import Text

def test_content_is_parsed_markup():
    p = Panel.from_markup("[bold]hi[/bold] there", title="T")
    assert isinstance(p, Panel) and isinstance(p.renderable, Text)
    assert p.renderable.plain == "hi there"
    assert any("bold" in str(s.style) for s in p.renderable.spans)
    assert p.title == "T"

def test_kwargs_pass_through():
    p = Panel.from_markup("x", expand=False, padding=2)
    assert p.expand is False and p.padding == 2
''',
    },
    "T4-filesize-parse": {
        "module": "rich/filesize.py",
        "spec": "Add a function `parse(size: str) -> int` to `rich/filesize.py`, the inverse of `decimal()`: it accepts "
                "the strings `decimal()` produces, such as '1 byte', '512 bytes', '1.5 kB' or '2.0 MB' (decimal units "
                "kB, MB, GB, TB, PB, EB, ZB, YB, powers of 1000), with or without the space before the unit, and "
                "returns the size in bytes rounded to the nearest integer. Anything else raises ValueError.",
        "regression": "tests/test_filesize.py",
        "accept": '''
import pytest
from rich.filesize import decimal, parse

def test_round_trip_examples():
    assert parse("1 byte") == 1
    assert parse("512 bytes") == 512
    assert parse("1.5 kB") == 1500
    assert parse("2.0MB") == 2_000_000
    assert parse(decimal(123_456_789)) == 123_500_000

def test_rejects_other_text():
    for bad in ("abc", "12 parsecs", ""):
        with pytest.raises(ValueError):
            parse(bad)
''',
    },
}
