import unittest

import torch

from tinygpt.data.batches import get_batch, split, to_tensor
from tinygpt.data.tokenizer import CharTokenizer


class DataTests(unittest.TestCase):
    def test_roundtrip_and_vocab(self):
        tok = CharTokenizer("hello world")
        self.assertEqual(tok.vocab_size, 8)
        self.assertEqual(tok.decode(tok.encode("low hello")), "low hello")

    def test_unknown_character(self):
        with self.assertRaises(ValueError):
            CharTokenizer("abc").encode("abz")

    def test_batches_are_shifted_by_one(self):
        data = torch.arange(100)
        x, y = get_batch(data, 8, 4, torch.Generator().manual_seed(0))
        self.assertEqual(tuple(x.shape), (4, 8))
        self.assertTrue(torch.equal(x[:, 1:], y[:, :-1]))
        self.assertTrue(torch.equal(y, x + 1))

    def test_split(self):
        tr, va = split(to_tensor(CharTokenizer("ab"), "ab" * 50))
        self.assertEqual((len(tr), len(va)), (90, 10))
