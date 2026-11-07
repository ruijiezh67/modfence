import math
import unittest

import torch

from tinygpt.config.settings import ModelConfig
from tinygpt.model.gpt import GPT


def tiny(vocab=11):
    torch.manual_seed(0)
    return GPT(ModelConfig(vocab_size=vocab, block_size=16, n_layer=2, n_head=2, n_embd=16))


class ModelTests(unittest.TestCase):
    def test_shapes_and_initial_loss(self):
        m = tiny()
        idx = torch.randint(11, (3, 16))
        logits, loss = m(idx, idx)
        self.assertEqual(tuple(logits.shape), (3, 16, 11))
        self.assertLess(abs(loss.item() - math.log(11)), 0.6)  # near uniform at init

    def test_causal(self):
        m = tiny().eval()
        a = torch.randint(11, (1, 10))
        b = a.clone()
        b[0, -1] = (b[0, -1] + 1) % 11
        la, _ = m(a)
        lb, _ = m(b)
        self.assertTrue(torch.allclose(la[0, :-1], lb[0, :-1], atol=1e-5))  # the future does not leak

    def test_too_long(self):
        with self.assertRaises(ValueError):
            tiny()(torch.zeros(1, 17, dtype=torch.long))
