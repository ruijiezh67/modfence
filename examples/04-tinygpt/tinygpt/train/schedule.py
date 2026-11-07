"""Learning rate per step: linear warmup, then constant."""

from tinygpt.config.settings import TrainConfig


def lr_at(step: int, cfg: TrainConfig) -> float:
    if cfg.warmup_steps and step < cfg.warmup_steps:
        return cfg.lr * (step + 1) / cfg.warmup_steps
    return cfg.lr
