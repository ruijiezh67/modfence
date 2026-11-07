"""The training loop: sample a batch, compute the loss, step the optimizer."""

import torch

from tinygpt.config.settings import ModelConfig, TrainConfig
from tinygpt.data.batches import get_batch
from tinygpt.train.schedule import lr_at


def make_optimizer(model, cfg: TrainConfig):
    """AdamW with weight decay on matrices only (not on biases, norms or embeddings' 1-d params)."""
    decay = [p for p in model.parameters() if p.requires_grad and p.dim() >= 2]
    no_decay = [p for p in model.parameters() if p.requires_grad and p.dim() < 2]
    groups = [{"params": decay, "weight_decay": cfg.weight_decay}, {"params": no_decay, "weight_decay": 0.0}]
    return torch.optim.AdamW(groups, lr=cfg.lr)


def train(model, data, model_cfg: ModelConfig, cfg: TrainConfig, log=None) -> list[float]:
    """Train in place and return the loss of every step."""
    torch.manual_seed(cfg.seed)
    gen = torch.Generator().manual_seed(cfg.seed)
    model.to(cfg.device).train()
    opt = make_optimizer(model, cfg)
    losses = []
    for step in range(cfg.steps):
        for group in opt.param_groups:
            group["lr"] = lr_at(step, cfg)
        x, y = get_batch(data, model_cfg.block_size, cfg.batch_size, gen)
        _, loss = model(x.to(cfg.device), y.to(cfg.device))
        opt.zero_grad(set_to_none=True)
        loss.backward()
        opt.step()
        losses.append(loss.item())
        if log and (step % 50 == 0 or step == cfg.steps - 1):
            log(step, losses[-1])
    return losses
