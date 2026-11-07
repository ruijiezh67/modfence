"""Character-level tokenizer: one id per distinct character of the training text."""


class CharTokenizer:
    def __init__(self, text: str):
        if not text:
            raise ValueError("cannot build a vocabulary from empty text")
        self.chars = sorted(set(text))
        self.stoi = {c: i for i, c in enumerate(self.chars)}

    @property
    def vocab_size(self) -> int:
        return len(self.chars)

    def encode(self, text: str) -> list[int]:
        try:
            return [self.stoi[c] for c in text]
        except KeyError as e:
            raise ValueError(f"character {e.args[0]!r} is not in the vocabulary") from None

    def decode(self, ids) -> str:
        return "".join(self.chars[int(i)] for i in ids)
