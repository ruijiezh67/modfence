# 00-iris: a machine-learning pipeline in six modules

A classifier for Fisher's Iris flowers, written with the Python standard library only, so it runs anywhere in about a second. It is the smallest project where the usual ML stages are separate modules, which makes it a good first project for modfence.

| Module | What it does | Uses |
|---|---|---|
| `iris/data` | Load `data/iris.csv`; deterministic stratified train/test split | nothing |
| `iris/features` | `Standardizer`: fit on the training rows only, then transform | nothing |
| `iris/model` | `SoftmaxRegression`: probabilities, predictions, loss, gradients, one step | nothing |
| `iris/train` | `train(model, X, y, epochs, lr)`: gradient descent, returns the loss per epoch | `model` |
| `iris/evaluate` | `accuracy`, `confusion_matrix` | nothing |
| `iris/cli` | `python -m iris train`: runs data → features → model/train → evaluate and prints the report | all of the above |

The stages pass plain lists to each other, so only `cli` knows the order and `model` knows nothing about training. That is why most tasks stay inside one or two modules.

## Run

```bash
python -m iris train        # test accuracy: 0.9778, then the confusion matrix
python -m unittest discover -s tests -t .
```

## Exercises

[`TASKS.md`](TASKS.md) has five, each with checkable acceptance lines: a k-NN model (`model`), per-class precision/recall/F1 (`evaluate`, `cli`), save/load as JSON (`model`, `cli`), k-fold cross-validation (`data`, `cli`), early stopping (`data`, `train`).

## Data

[`DATA.md`](DATA.md): the UCI copy of Fisher's Iris data (CC BY 4.0), its source, checksum and the two rows known to differ from Fisher's 1936 paper. Nothing in this folder is synthetic.
