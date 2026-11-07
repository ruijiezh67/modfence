"""Standardize each feature to zero mean and unit variance using training statistics."""

import math


class Standardizer:
    """Learn per-feature mean and standard deviation, then rescale rows with them."""

    def __init__(self) -> None:
        """Create an unfitted scaler."""
        self.means: list[float] | None = None
        self.stds: list[float] | None = None

    def fit(self, X: list[list[float]]) -> "Standardizer":
        """Compute the mean and population standard deviation of each column of X."""
        if not X:
            raise ValueError("cannot fit on an empty dataset")
        n, d = len(X), len(X[0])
        self.means = [sum(row[j] for row in X) / n for j in range(d)]
        self.stds = []
        for j in range(d):
            var = sum((row[j] - self.means[j]) ** 2 for row in X) / n
            self.stds.append(math.sqrt(var) or 1.0)
        return self

    def transform(self, X: list[list[float]]) -> list[list[float]]:
        """Rescale rows with the fitted statistics (never refits)."""
        if self.means is None or self.stds is None:
            raise RuntimeError("Standardizer must be fitted before transform")
        return [[(v - m) / s for v, m, s in zip(row, self.means, self.stds)] for row in X]

    def fit_transform(self, X: list[list[float]]) -> list[list[float]]:
        """Fit on X and return X rescaled."""
        return self.fit(X).transform(X)
