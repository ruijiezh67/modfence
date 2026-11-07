"""Mean loss over a few random held-out batches."""

import torch

from tinygpt.data.batches import get_batch


@torch.no_grad()
def estimate_loss(model, data, block_size: int, batch_size: int = 16, iters: int = 10, seed: int = 0) -> float:
    was_training = model.training
    model.eval()
    gen = torch.Generator().manual_seed(seed)
    device = next(model.parameters()).device
    total = 0.0
    for _ in range(iters):
        x, y = get_batch(data, block_size, batch_size, gen)
        _, loss = model(x.to(device), y.to(device))
        total += loss.item()
    model.train(was_training)
    return total / iters
