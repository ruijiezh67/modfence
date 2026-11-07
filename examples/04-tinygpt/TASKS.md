# Tasks for 04-tinygpt

Each task lists its target module(s). Acceptance items are checks you can run with `python -m unittest` or a few lines of Python. Training checks use CPU and fixed seeds.

## 1. Top-k sampling (single module: `eval`)

Target: `tinygpt.eval` only.

Build: `generate` and `sample_text` take `top_k: int | None = None`. With `top_k`, only the k most likely tokens can be sampled.

Acceptance:
- With `top_k=1` and any temperature above 0, `generate` returns the same tokens as greedy (`temperature=0`)
- With `top_k=None`, results are unchanged from today for the same seed
- `top_k` larger than the vocabulary behaves like `None`

## 2. Cosine learning-rate decay (single module: `train`)

Target: `tinygpt.train` only.

Build: after warmup, `lr_at` decays from `cfg.lr` to `0.1 * cfg.lr` along a cosine over the remaining steps (`cfg.steps`).

Acceptance:
- Warmup values are unchanged: with `lr=1, warmup_steps=4` the first four values are `0.25, 0.5, 0.75, 1.0`
- At the last step (`steps - 1`) the rate is `0.1 * lr` (within 1e-6)
- The rate never increases after warmup

## 3. Weight tying (single module: `model`)

Target: `tinygpt.model` only.

Build: the language-model head shares its weight with the token embedding.

Acceptance:
- `model.head.weight is model.tok_emb.weight`
- `num_params()` counts the shared weight once: it drops by exactly `vocab_size * n_embd`
- The existing tests still pass

## 4. Gradient accumulation and clipping (crosses modules: `config`, `train`)

Target: `tinygpt.config`, `tinygpt.train`.

Build: `TrainConfig` gets `grad_accum: int = 1` and `grad_clip: float | None = 1.0`. The loop runs `grad_accum` micro-batches of `batch_size` per optimizer step, averaging their losses, and clips the global gradient norm when `grad_clip` is set. `steps` still counts optimizer steps; the returned loss per step is the mean over its micro-batches.

Acceptance:
- With `grad_accum=1, grad_clip=None` the losses equal today's for the same seed
- With `grad_accum=4`, `train` returns exactly `steps` losses and draws `4 * steps` batches
- With `grad_clip=1e-9`, the parameters move less than a tenth as far (summed absolute change over 5 steps) as with `grad_clip=None`. (AdamW rescales gradients, so a tiny clip only shrinks steps once the gradient falls below Adam's `eps`.)
- The overfit test still passes with `grad_accum=2`

## 5. KV cache for generation (crosses modules: `model`, `eval`)

Target: `tinygpt.model`, `tinygpt.eval`.

Build: the attention layers can keep the keys and values of earlier positions, so generation feeds one new token per step instead of the whole window. `GPT.forward` takes an optional cache and a start position; `generate` uses it until the window is full, then falls back to recomputing the window.

Acceptance:
- Greedy `generate` with the cache returns exactly the same tokens as without it, for 40 new tokens from a 3-token prompt with `block_size=16` (so the window fills and slides)
- Training (`forward` without a cache) gives the same logits as before
- Generating 32 tokens with the cache makes one forward pass over the prompt and then one single-token pass per new token while the window has room
