import unittest

from tinygpt.config.settings import ModelConfig, TrainConfig
from tinygpt.data.batches import to_tensor
from tinygpt.data.tokenizer import CharTokenizer
from tinygpt.model.gpt import GPT
from tinygpt.train.loop import train
from tinygpt.train.schedule import lr_at


class TrainTests(unittest.TestCase):
    def test_overfits_a_pattern(self):
        text = "abcd" * 64
        tok = CharTokenizer(text)
        mcfg = ModelConfig(vocab_size=tok.vocab_size, block_size=8, n_layer=1, n_head=2, n_embd=16)
        losses = train(GPT(mcfg), to_tensor(tok, text), mcfg, TrainConfig(steps=120, batch_size=8, lr=1e-2))
        self.assertLess(sum(losses[-10:]) / 10, 0.3 * losses[0])

    def test_warmup(self):
        cfg = TrainConfig(lr=1.0, warmup_steps=4)
        self.assertEqual([lr_at(s, cfg) for s in range(6)], [0.25, 0.5, 0.75, 1.0, 1.0, 1.0])
