"""Hyperparameters. Defaults are small enough to train on a CPU in seconds."""

from dataclasses import dataclass


@dataclass
class ModelConfig:
    vocab_size: int = 0
    block_size: int = 32
    n_layer: int = 2
    n_head: int = 2
    n_embd: int = 32
    dropout: float = 0.0


@dataclass
class TrainConfig:
    steps: int = 200
    batch_size: int = 16
    lr: float = 3e-3
    warmup_steps: int = 20
    weight_decay: float = 0.01
    seed: int = 0
    device: str = "cpu"
