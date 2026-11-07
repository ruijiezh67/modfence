"""The GPT: token and position embeddings, a stack of blocks, and a language-model head."""

import torch
import torch.nn as nn
import torch.nn.functional as F

from tinygpt.config.settings import ModelConfig
from tinygpt.model.block import Block


class GPT(nn.Module):
    def __init__(self, cfg: ModelConfig):
        super().__init__()
        if cfg.vocab_size <= 0:
            raise ValueError("set ModelConfig.vocab_size from the tokenizer")
        self.cfg = cfg
        self.tok_emb = nn.Embedding(cfg.vocab_size, cfg.n_embd)
        self.pos_emb = nn.Embedding(cfg.block_size, cfg.n_embd)
        self.drop = nn.Dropout(cfg.dropout)
        self.blocks = nn.ModuleList(Block(cfg) for _ in range(cfg.n_layer))
        self.ln_f = nn.LayerNorm(cfg.n_embd)
        self.head = nn.Linear(cfg.n_embd, cfg.vocab_size, bias=False)

    def forward(self, idx, targets=None):
        """Logits of shape (B, T, vocab), and the cross-entropy loss when targets are given."""
        B, T = idx.shape
        if T > self.cfg.block_size:
            raise ValueError(f"sequence length {T} exceeds block_size {self.cfg.block_size}")
        pos = torch.arange(T, device=idx.device)
        x = self.drop(self.tok_emb(idx) + self.pos_emb(pos))
        for block in self.blocks:
            x = block(x)
        logits = self.head(self.ln_f(x))
        loss = None
        if targets is not None:
            loss = F.cross_entropy(logits.view(-1, logits.size(-1)), targets.view(-1))
        return logits, loss

    def num_params(self) -> int:
        return sum(p.numel() for p in self.parameters())
