# Tasks for 00-iris

Each task lists its target module(s). Acceptance examples use the command `python -m iris ...` run from this folder and its printed output, or the equivalent function call. "The default split" means `train_test_split(rows, y, 0.3, seed=0)` with a `Standardizer` fitted on the training rows, exactly as `run_pipeline()` does it.

## 1. k-nearest-neighbours classifier (single module: `model`)

Target: `iris.model` only.

Build: add `iris/model/knn.py` with a class `KNearestNeighbours(k=5)` that has `fit(X, y)` (stores the rows, returns `self`), `predict_proba(X)` (the share of the k nearest training rows in each class, by Euclidean distance) and `predict(X)` (the class with the most votes; a tie goes to the smallest class index). It must not import anything from `iris.train`, `iris.evaluate` or `iris.cli`.

Acceptance:
- `KNearestNeighbours(k=1).fit([[0, 0], [1, 1]], [0, 1]).predict([[0.1, 0], [0.9, 1]])` returns `[0, 1]`
- with `k=3`, every row of `predict_proba` sums to 1 and every value is 0, 1/3, 2/3 or 1
- `KNearestNeighbours(k=2).fit([[0], [2]], [1, 0]).predict([[1]])` returns `[0]` (tie goes to the smaller class index)
- on the default split, `KNearestNeighbours(k=5)` reaches test accuracy of at least 0.95
- modfence still shows no edge from `iris/model` to any other `iris` module

## 2. Per-class precision, recall and F1 (crosses modules: `evaluate`, `cli`)

Target: `iris.evaluate`, `iris.cli`.

Build: add `precision_recall_f1(y_true, y_pred, n_classes)` to `iris/evaluate/metrics.py`, returning one `(precision, recall, f1)` tuple per class, with 0/0 defined as 0.0. Make `python -m iris train` print, after the confusion matrix, one line per class (name, then precision, recall and F1 with 4 decimals) and a final `macro avg` line with the unweighted mean of each column.

Acceptance:
- `precision_recall_f1([0, 0, 1, 1], [0, 1, 1, 1], 2)` equals `[(1.0, 0.5, 0.6667), (0.6667, 1.0, 0.8)]` to 4 decimals
- `precision_recall_f1([0, 1], [0, 0], 2)[1]` is `(0.0, 0.0, 0.0)` and raises no error
- `python -m iris train` still prints `test accuracy: 0.9778`
- the `Iris-setosa` line shows `1.0000 1.0000 1.0000` and the `Iris-versicolor` line shows `1.0000 0.9333 0.9655`
- the output contains a line starting with `macro avg`

## 3. Save and load a trained model as JSON (crosses modules: `model`, `cli`)

Target: `iris.model`, `iris.cli`.

Build: give `SoftmaxRegression` a `to_dict()` method and a `from_dict(d)` classmethod (weights, biases, sizes). Add `--save PATH` to `train`, writing one JSON file with the model, the scaler's means and standard deviations, and the class names. Add a `predict` command: `python -m iris predict --model PATH SL SW PL PW` prints the predicted species for one flower.

Acceptance:
- `SoftmaxRegression.from_dict(m.to_dict()).predict_proba(X)` equals `m.predict_proba(X)` for a trained `m`, and `json.dumps(m.to_dict())` succeeds
- `python -m iris train --save model.json` exits 0, prints the same report as `python -m iris train`, and creates `model.json`
- after that, `python -m iris predict --model model.json 5.1 3.5 1.4 0.2` prints `Iris-setosa`
- `python -m iris predict --model model.json 5.7 2.8 4.1 1.3` prints `Iris-versicolor`
- `python -m iris predict --model model.json 6.7 3.0 5.2 2.3` prints `Iris-virginica`
- `python -m iris predict --model missing.json 5.1 3.5 1.4 0.2` exits 1 and prints an error starting with `error:`

## 4. k-fold cross-validation command (crosses modules: `data`, `cli`)

Target: `iris.data`, `iris.cli`.

Build: add `stratified_k_fold(y, k, seed=0)` to `iris/data/split.py`, returning a list of k `(train_indices, test_indices)` pairs in which every class is spread as evenly as possible over the test folds. Add a `cv` command: `python -m iris cv --folds K` trains a fresh model on each fold (the scaler is fitted on that fold's training rows only), prints one `fold N: accuracy X.XXXX` line per fold and a final `mean accuracy: X.XXXX (std X.XXXX)` line.

Acceptance:
- on the 150 Iris labels, `stratified_k_fold(y, 5, seed=0)` returns 5 pairs; each test fold has 30 indices, 10 from each class
- the test folds are pairwise disjoint and together are exactly `range(150)`; in each pair the train and test indices are disjoint and together have 150 entries
- the same seed gives the same folds
- `stratified_k_fold(y, 1)` and `stratified_k_fold(y, 51)` raise `ValueError` (51 folds exceed the 50 rows of a class)
- `python -m iris cv --folds 5` exits 0, prints 5 `fold` lines and a `mean accuracy` of at least 0.90
- `python -m iris train` output is unchanged

## 5. Early stopping on a validation split (crosses modules: `data`, `train`)

Target: `iris.data`, `iris.train`.

Build: add `train_val_test_split(X, y, val_fraction=0.2, test_fraction=0.2, seed=0)` to `iris/data/split.py`, a stratified three-way split returning `(X_train, X_val, X_test, y_train, y_val, y_test)`. Add `train_with_early_stopping(model, X, y, X_val, y_val, epochs, lr, patience)` to `iris/train/loop.py`: after every gradient step it records the training loss and the validation loss, stops as soon as `patience` consecutive epochs pass without a new lowest validation loss, puts the model back to its weights from the best epoch, and returns `{"train_loss": [...], "val_loss": [...], "best_epoch": int}`. The existing `train` function keeps its behaviour.

Acceptance:
- on Iris, `train_val_test_split(rows, y, 0.2, 0.2, seed=0)` gives 90 / 30 / 30 rows, with 10 of each class in both the validation and the test part; the three parts are disjoint and together hold all 150 rows
- the next checks use the default split's scaled training rows as `X, y` and its scaled test rows as `X_val, y_val`, with `SoftmaxRegression(4, 3, seed=0)`, `lr=0.5`, `patience=5`
- `len(result["train_loss"]) == len(result["val_loss"])`, and `result["val_loss"][result["best_epoch"]] == min(result["val_loss"])`
- after the call, `model.loss(X_val, y_val)` equals `min(result["val_loss"])` (the best weights were restored)
- with deliberately wrong validation labels (`[(t + 1) % 3 for t in y_val]`) and `epochs=50`, training stops after 6 epochs with `best_epoch == 0`
- with the real validation labels and `epochs=50`, all 50 epochs run and `best_epoch == 49` (the validation loss keeps falling)
- `python -m iris train` still prints `test accuracy: 0.9778`
