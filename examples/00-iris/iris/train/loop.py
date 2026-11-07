"""Plain full-batch gradient descent training loop."""

from iris.model.softmax import SoftmaxRegression


def train(model: SoftmaxRegression, X: list[list[float]], y: list[int], epochs: int = 200,
          lr: float = 0.5) -> list[float]:
    """Run `epochs` gradient steps on (X, y) and return the loss recorded at each one."""
    if epochs < 1:
        raise ValueError("epochs must be at least 1")
    if lr <= 0:
        raise ValueError("lr must be positive")
    return [model.step(X, y, lr) for _ in range(epochs)]
