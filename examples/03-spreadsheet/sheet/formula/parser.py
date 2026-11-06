"""Recursive-descent formula parser.

Grammar::

    formula = "=" expr
    expr    = term (("+" | "-") term)*
    term    = unary (("*" | "/") unary)*
    unary   = "-" unary | primary
    primary = NUMBER | CELL [":" CELL] | NAME "(" [expr ("," expr)*] ")" | "(" expr ")"

Raises FormulaError for syntax problems. A cell name outside the grid raises
InvalidAddress, which the engine reports as ``#REF!``.
"""

import re

from sheet.cells.address import parse_address
from sheet.cells.ranges import make_range
from sheet.formula.lexer import FormulaError, Kind, Token, tokenize
from sheet.formula.nodes import BinOp, Call, Neg, Node, Number, RangeRef, Ref

_CELL_NAME = re.compile(r"[A-Za-z]+[0-9]+")


class _Parser:
    def __init__(self, tokens: list[Token]) -> None:
        self._tokens = tokens
        self._pos = 0

    @property
    def _cur(self) -> Token:
        return self._tokens[self._pos]

    def _next(self) -> Token:
        token = self._cur
        if token.kind is not Kind.END:
            self._pos += 1
        return token

    def _expect(self, kind: Kind) -> Token:
        if self._cur.kind is not kind:
            raise FormulaError(f"expected {kind.value!r} at position {self._cur.pos}")
        return self._next()

    def parse(self) -> Node:
        node = self._expr()
        self._expect(Kind.END)
        return node

    def _is_op(self, *ops: str) -> bool:
        return self._cur.kind is Kind.OP and self._cur.text in ops

    def _expr(self) -> Node:
        node = self._term()
        while self._is_op("+", "-"):
            op = self._next().text
            node = BinOp(op, node, self._term())
        return node

    def _term(self) -> Node:
        node = self._unary()
        while self._is_op("*", "/"):
            op = self._next().text
            node = BinOp(op, node, self._unary())
        return node

    def _unary(self) -> Node:
        if self._is_op("-"):
            self._next()
            return Neg(self._unary())
        return self._primary()

    def _primary(self) -> Node:
        token = self._next()
        if token.kind is Kind.NUMBER:
            return Number(float(token.text))
        if token.kind is Kind.LPAREN:
            node = self._expr()
            self._expect(Kind.RPAREN)
            return node
        if token.kind is Kind.NAME:
            if self._cur.kind is Kind.LPAREN:
                return self._call(token.text)
            return self._reference(token)
        raise FormulaError(f"unexpected {token.text or 'end of formula'!r}")

    def _call(self, name: str) -> Node:
        self._expect(Kind.LPAREN)
        args: list[Node] = []
        if self._cur.kind is not Kind.RPAREN:
            args.append(self._expr())
            while self._cur.kind is Kind.COMMA:
                self._next()
                args.append(self._expr())
        self._expect(Kind.RPAREN)
        return Call(name.upper(), tuple(args))

    def _reference(self, token: Token) -> Node:
        if not _CELL_NAME.fullmatch(token.text):
            raise FormulaError(f"unknown name {token.text!r}")
        first = parse_address(token.text)
        if self._cur.kind is not Kind.COLON:
            return Ref(first)
        self._next()
        second = self._expect(Kind.NAME)
        if not _CELL_NAME.fullmatch(second.text):
            raise FormulaError(f"expected a cell after ':' but got {second.text!r}")
        return RangeRef(make_range(first, parse_address(second.text)))


def parse_formula(text: str) -> Node:
    """Parse a formula such as ``"=A1+B2*2"``; the leading ``=`` is optional."""
    body = text.strip()
    if body.startswith("="):
        body = body[1:]
    return _Parser(tokenize(body)).parse()
