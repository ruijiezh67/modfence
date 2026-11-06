"""Formula lexer."""

import re
from dataclasses import dataclass
from enum import Enum


class FormulaError(ValueError):
    """Raised for formulas that cannot be tokenized or parsed."""


class Kind(Enum):
    """Token categories."""

    NUMBER = "number"
    NAME = "name"
    OP = "op"
    LPAREN = "("
    RPAREN = ")"
    COMMA = ","
    COLON = ":"
    END = "end"


@dataclass(frozen=True)
class Token:
    """A token with its text and position in the formula."""

    kind: Kind
    text: str
    pos: int


_PATTERN = re.compile(
    r"\s*(?:(?P<number>\d+(?:\.\d+)?|\.\d+)|(?P<name>[A-Za-z][A-Za-z0-9]*)"
    r"|(?P<op>[-+*/])|(?P<lparen>\()|(?P<rparen>\))|(?P<comma>,)|(?P<colon>:))"
)

_KINDS = {
    "number": Kind.NUMBER,
    "name": Kind.NAME,
    "op": Kind.OP,
    "lparen": Kind.LPAREN,
    "rparen": Kind.RPAREN,
    "comma": Kind.COMMA,
    "colon": Kind.COLON,
}


def tokenize(text: str) -> list[Token]:
    """Tokenize formula text (without the leading ``=``)."""
    tokens: list[Token] = []
    pos = 0
    while pos < len(text):
        if text[pos:].strip() == "":
            break
        match = _PATTERN.match(text, pos)
        if match is None:
            raise FormulaError(f"unexpected character {text[pos:].strip()[0]!r}")
        group = match.lastgroup
        tokens.append(Token(_KINDS[group], match.group(group), match.start(group)))
        pos = match.end()
    tokens.append(Token(Kind.END, "", len(text)))
    return tokens
