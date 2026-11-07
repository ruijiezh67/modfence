"""Split rows into train and test sets, keeping each class's share the same in both."""

import random


def train_test_split(X: list, y: list, test_fraction: float = 0.3, seed: int = 0) -> tuple[list, list, list, list]:
    """Deterministic stratified split; return (X_train, X_test, y_train, y_test)."""
    if not 0.0 < test_fraction < 1.0:
        raise ValueError("test_fraction must be between 0 and 1")
    if len(X) != len(y):
        raise ValueError("X and y must have the same length")
    rng = random.Random(seed)
    by_class: dict = {}
    for i, label in enumerate(y):
        by_class.setdefault(label, []).append(i)
    train_idx, test_idx = [], []
    for label in sorted(by_class):
        idx = by_class[label]
        rng.shuffle(idx)
        n_test = round(len(idx) * test_fraction)
        test_idx.extend(idx[:n_test])
        train_idx.extend(idx[n_test:])
    train_idx.sort()
    test_idx.sort()
    return ([X[i] for i in train_idx], [X[i] for i in test_idx],
            [y[i] for i in train_idx], [y[i] for i in test_idx])
