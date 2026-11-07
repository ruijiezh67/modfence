import contextlib
import io
import unittest

import torch

from tinygpt.cli.run import main
from tinygpt.config.settings import ModelConfig
from tinygpt.data.tokenizer import CharTokenizer
from tinygpt.eval.sample import generate, sample_text
from tinygpt.model.gpt import GPT


class EvalTests(unittest.TestCase):
    def setUp(self):
        torch.manual_seed(0)
        self.tok = CharTokenizer("hello world")
        self.m = GPT(ModelConfig(vocab_size=self.tok.vocab_size, block_size=8, n_layer=1, n_head=2, n_embd=16))

    def test_greedy_is_deterministic(self):
        idx = torch.tensor([self.tok.encode("he")])
        a = generate(self.m, idx, 12, temperature=0)
        b = generate(self.m, idx, 12, temperature=0)
        self.assertEqual(tuple(a.shape), (1, 14))
        self.assertTrue(torch.equal(a, b))

    def test_sample_text_keeps_prompt(self):
        s = sample_text(self.m, self.tok, "hel", 20, temperature=1.0, seed=1)
        self.assertTrue(s.startswith("hel"))
        self.assertEqual(len(s), 23)

    def test_cli_smoke(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(main(["--steps", "5", "--sample", "10"]), 0)
        self.assertIn("val loss", out.getvalue())
