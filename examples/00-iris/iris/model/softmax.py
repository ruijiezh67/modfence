"""Multinomial logistic regression (softmax regression) in pure Python."""

import math
import random


def softmax(logits: list[float]) -> list[float]:
    """Turn a list of scores into probabilities that sum to 1 (numerically stable)."""
    top = max(logits)
    exps = [math.exp(z - top) for z in logits]
    total = sum(exps)
    return [e / total for e in exps]


class SoftmaxRegression:
    """Linear model with one weight row and one bias per class."""

    def __init__(self, n_features: int, n_classes: int, seed: int = 0) -> None:
        """Initialise small random weights (seeded) and zero biases."""
        rng = random.Random(seed)
        self.n_features = n_features
        self.n_classes = n_classes
        self.weights = [[rng.gauss(0.0, 0.01) for _ in range(n_features)] for _ in range(n_classes)]
        self.biases = [0.0] * n_classes

    def predict_proba(self, X: list[list[float]]) -> list[list[float]]:
        """Return one probability per class for each row of X."""
        out = []
        for row in X:
            logits = [sum(w * x for w, x in zip(wk, row)) + b for wk, b in zip(self.weights, self.biases)]
            out.append(softmax(logits))
        return out

    def predict(self, X: list[list[float]]) -> list[int]:
        """Return the most probable class index for each row of X."""
        return [max(range(self.n_classes), key=p.__getitem__) for p in self.predict_proba(X)]

    def loss(self, X: list[list[float]], y: list[int]) -> float:
        """Mean cross-entropy of the true classes y under the model."""
        probs = self.predict_proba(X)
        return -sum(math.log(max(p[t], 1e-12)) for p, t in zip(probs, y)) / len(y)

    def gradients(self, X: list[list[float]], y: list[int]) -> tuple[list[list[float]], list[float]]:
        """Gradient of the mean cross-entropy with respect to the weights and biases."""
        n = len(X)
        grad_w = [[0.0] * self.n_features for _ in range(self.n_classes)]
        grad_b = [0.0] * self.n_classes
        for row, p, t in zip(X, self.predict_proba(X), y):
            for k in range(self.n_classes):
                err = (p[k] - (1.0 if k == t else 0.0)) / n
                grad_b[k] += err
                gw = grad_w[k]
                for j, x in enumerate(row):
                    gw[j] += err * x
        return grad_w, grad_b

    def step(self, X: list[list[float]], y: list[int], lr: float) -> float:
        """Take one full-batch gradient descent step; return the loss before the step."""
        loss = self.loss(X, y)
        grad_w, grad_b = self.gradients(X, y)
        for k in range(self.n_classes):
            for j in range(self.n_features):
                self.weights[k][j] -= lr * grad_w[k][j]
            self.biases[k] -= lr * grad_b[k]
        return loss
