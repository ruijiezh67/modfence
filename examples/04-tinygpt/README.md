# 04-tinygpt

A tiny character-level GPT, trained with PyTorch, split the way larger training codebases are: config, data, model, train, eval and a CLI as separate modules. It trains on a CPU in seconds, so the exercises are about code structure, not GPUs.

| Module | Job | Depends on |
|---|---|---|
| `tinygpt.config` | Hyperparameters (`ModelConfig`, `TrainConfig`) | nothing |
| `tinygpt.data` | Character tokenizer, token tensor, random (x, y) batches | nothing |
| `tinygpt.model` | Attention, transformer block, the `GPT` module | `config` |
| `tinygpt.train` | AdamW, warmup schedule, the training loop | `config`, `data` |
| `tinygpt.eval` | Held-out loss and generation | `data` |
| `tinygpt.cli` | `python -m tinygpt`: train, report, sample | all of the above |

Requires Python 3.10+ and PyTorch 2.x (`torch`). It is the only example that is not standard-library only.

```
python -m tinygpt --steps 300 --sample 200
python -m unittest discover -s tests -t .
```

**Training text.** `data/tiny.txt` is 20 short English lines written for this example (four of them are well-known pangrams), repeated 6 times, about 6 KB. It is not taken from any dataset. It is only there so a run finishes in seconds and the loss visibly falls; it says nothing about model quality.
