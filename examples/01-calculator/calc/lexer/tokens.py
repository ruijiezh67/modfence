"""Token types shared by the lexer and the parser."""

from dataclasses import dataclass
from enum import Enum


class Kind(Enum):
    """The category of a token."""

    NUMBER = "number"
    PLUS = "+"
    MINUS = "-"
    STAR = "*"
    SLASH = "/"
    LPAREN = "("
    RPAREN = ")"
    END = "end"


@dataclass(frozen=True)
class Token:
    """One lexical unit: its kind, its source text and its position."""

    kind: Kind
    text: str
    pos: int
