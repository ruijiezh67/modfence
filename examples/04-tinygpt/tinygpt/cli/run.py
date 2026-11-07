"""argparse front end: python -m tinygpt [--steps N] [--sample N] ..."""

import argparse
import os

from tinygpt.config.settings import ModelConfig, TrainConfig
from tinygpt.data.batches import split, to_tensor
from tinygpt.data.tokenizer import CharTokenizer
from tinygpt.eval.loss import estimate_loss
from tinygpt.eval.sample import sample_text
from tinygpt.model.gpt import GPT
from tinygpt.train.loop import train

DEFAULT_TEXT = os.path.join(os.path.dirname(__file__), "..", "..", "data", "tiny.txt")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="tinygpt", description="Train a tiny character-level GPT")
    p.add_argument("--text", default=DEFAULT_TEXT, help="training text file")
    p.add_argument("--steps", type=int, default=200)
    p.add_argument("--sample", type=int, default=200, help="characters to generate after training")
    p.add_argument("--prompt", default="T")
    p.add_argument("--temperature", type=float, default=0.8)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--device", default="cpu")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    with open(args.text, encoding="utf-8") as f:
        text = f.read()
    tok = CharTokenizer(text)
    train_data, val_data = split(to_tensor(tok, text))
    mcfg = ModelConfig(vocab_size=tok.vocab_size)
    tcfg = TrainConfig(steps=args.steps, seed=args.seed, device=args.device)
    model = GPT(mcfg)
    print(f"{model.num_params():,} parameters, vocab {tok.vocab_size}, {len(text):,} characters")
    train(model, train_data, mcfg, tcfg, log=lambda s, l: print(f"step {s} loss {l:.3f}"))
    print(f"val loss {estimate_loss(model, val_data, mcfg.block_size):.3f}")
    if args.sample:
        print(sample_text(model, tok, args.prompt, args.sample, args.temperature, args.seed))
    return 0
