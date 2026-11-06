"""Scanner: converts a source string into a list of tokens."""

from calc.lexer.tokens import Kind, Token

SYMBOLS = {
    "+": Kind.PLUS,
    "-": Kind.MINUS,
    "*": Kind.STAR,
    "/": Kind.SLASH,
    "(": Kind.LPAREN,
    ")": Kind.RPAREN,
}


class LexError(ValueError):
    """Raised when the source contains a character or number we cannot read."""


def tokenize(source: str) -> list[Token]:
    """Return the tokens of ``source``, always ending with an END token."""
    tokens: list[Token] = []
    i = 0
    while i < len(source):
        ch = source[i]
        if ch.isspace():
            i += 1
        elif ch.isdigit() or ch == ".":
            j = i
            while j < len(source) and (source[j].isdigit() or source[j] == "."):
                j += 1
            text = source[i:j]
            if text.count(".") > 1 or text == ".":
                raise LexError(f"malformed number {text!r} at position {i}")
            tokens.append(Token(Kind.NUMBER, text, i))
            i = j
        elif ch in SYMBOLS:
            tokens.append(Token(SYMBOLS[ch], ch, i))
            i += 1
        else:
            raise LexError(f"unexpected character {ch!r} at position {i}")
    tokens.append(Token(Kind.END, "", len(source)))
    return tokens
