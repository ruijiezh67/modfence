"""Turn text into a token tensor and sample (input, target) blocks from it."""

import torch

from tinygpt.data.tokenizer import CharTokenizer


def to_tensor(tok: CharTokenizer, text: str) -> torch.Tensor:
    return torch.tensor(tok.encode(text), dtype=torch.long)


def split(data: torch.Tensor, train_frac: float = 0.9):
    n = int(len(data) * train_frac)
    return data[:n], data[n:]


def get_batch(data: torch.Tensor, block_size: int, batch_size: int, generator=None):
    """x is a batch of blocks, y the same blocks shifted one token to the right."""
    if len(data) <= block_size:
        raise ValueError(f"need more than {block_size} tokens, got {len(data)}")
    ix = torch.randint(len(data) - block_size, (batch_size,), generator=generator)
    x = torch.stack([data[i:i + block_size] for i in ix])
    y = torch.stack([data[i + 1:i + block_size + 1] for i in ix])
    return x, y
