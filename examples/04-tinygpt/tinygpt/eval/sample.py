"""Autoregressive generation: feed the model its own output one token at a time."""

import torch
import torch.nn.functional as F

from tinygpt.data.tokenizer import CharTokenizer


@torch.no_grad()
def generate(model, idx, max_new_tokens: int, temperature: float = 1.0, generator=None):
    """Append max_new_tokens tokens to idx (B, T). temperature 0 means greedy."""
    model.eval()
    block = model.cfg.block_size
    for _ in range(max_new_tokens):
        logits, _ = model(idx[:, -block:])
        logits = logits[:, -1, :]
        if temperature == 0:
            nxt = logits.argmax(dim=-1, keepdim=True)
        else:
            probs = F.softmax(logits / temperature, dim=-1)
            nxt = torch.multinomial(probs, 1, generator=generator)
        idx = torch.cat([idx, nxt], dim=1)
    return idx


def sample_text(model, tok: CharTokenizer, prompt: str, n: int, temperature: float = 1.0, seed: int = 0) -> str:
    device = next(model.parameters()).device
    idx = torch.tensor([tok.encode(prompt)], dtype=torch.long, device=device)
    gen = torch.Generator(device=device).manual_seed(seed)
    return tok.decode(generate(model, idx, n, temperature, gen)[0].tolist())
