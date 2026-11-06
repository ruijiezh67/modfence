"""Recursive-descent parser.

Grammar::

    expr    = term (("+" | "-") term)*
    term    = unary (("*" | "/") unary)*
    unary   = "-" unary | primary
    primary = NUMBER | "(" expr ")"
"""

from calc.lexer.scanner import tokenize
from calc.lexer.tokens import Kind, Token
from calc.parser.nodes import BinOp, Node, Num, UnaryOp


class ParseError(ValueError):
    """Raised when the tokens do not form a valid expression."""


class Parser:
    """Parses a token list into an AST."""

    def __init__(self, tokens: list[Token]) -> None:
        self._tokens = tokens
        self._pos = 0

    @property
    def _current(self) -> Token:
        return self._tokens[self._pos]

    def _advance(self) -> Token:
        token = self._current
        if token.kind is not Kind.END:
            self._pos += 1
        return token

    def parse(self) -> Node:
        """Parse the whole token list and return the root node."""
        node = self._expr()
        if self._current.kind is not Kind.END:
            raise ParseError(
                f"unexpected {self._current.text!r} at position {self._current.pos}"
            )
        return node

    def _expr(self) -> Node:
        node = self._term()
        while self._current.kind in (Kind.PLUS, Kind.MINUS):
            op = self._advance()
            node = BinOp(op.text, node, self._term())
        return node

    def _term(self) -> Node:
        node = self._unary()
        while self._current.kind in (Kind.STAR, Kind.SLASH):
            op = self._advance()
            node = BinOp(op.text, node, self._unary())
        return node

    def _unary(self) -> Node:
        if self._current.kind is Kind.MINUS:
            self._advance()
            return UnaryOp("-", self._unary())
        return self._primary()

    def _primary(self) -> Node:
        token = self._current
        if token.kind is Kind.NUMBER:
            self._advance()
            return Num(float(token.text) if "." in token.text else int(token.text))
        if token.kind is Kind.LPAREN:
            self._advance()
            node = self._expr()
            if self._current.kind is not Kind.RPAREN:
                raise ParseError(f"expected ')' at position {self._current.pos}")
            self._advance()
            return node
        raise ParseError(f"expected a number or '(' at position {token.pos}")


def parse(source: str) -> Node:
    """Tokenize and parse ``source`` into an AST."""
    return Parser(tokenize(source)).parse()
