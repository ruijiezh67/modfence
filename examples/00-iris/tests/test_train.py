"""Tests for the gradient descent training loop."""

import unittest

from iris.data.load import encode_labels, load_iris
from iris.features.scale import Standardizer
from iris.model.softmax import SoftmaxRegression
from iris.train.loop import train


class TrainTests(unittest.TestCase):
    """Training on the full Iris data lowers the loss, reproducibly."""

    def setUp(self):
        """Load, encode and standardise the full dataset."""
        rows, labels = load_iris()
        self.y, _ = encode_labels(labels)
        self.X = Standardizer().fit_transform(rows)

    def test_history_length(self):
        """One loss per epoch."""
        losses = train(SoftmaxRegression(4, 3), self.X, self.y, epochs=10, lr=0.5)
        self.assertEqual(len(losses), 10)

    def test_loss_falls(self):
        """The loss falls from about log(3) to well below 0.3, and never rises."""
        losses = train(SoftmaxRegression(4, 3), self.X, self.y, epochs=100, lr=0.5)
        self.assertGreater(losses[0], 1.0)
        self.assertLess(losses[-1], 0.3)
        self.assertTrue(all(b <= a + 1e-12 for a, b in zip(losses, losses[1:])))

    def test_deterministic(self):
        """Two runs with the same seed give identical loss histories."""
        a = train(SoftmaxRegression(4, 3, seed=2), self.X, self.y, epochs=20)
        b = train(SoftmaxRegression(4, 3, seed=2), self.X, self.y, epochs=20)
        self.assertEqual(a, b)

    def test_bad_arguments(self):
        """Zero epochs or a non-positive learning rate are rejected."""
        with self.assertRaises(ValueError):
            train(SoftmaxRegression(4, 3), self.X, self.y, epochs=0)
        with self.assertRaises(ValueError):
            train(SoftmaxRegression(4, 3), self.X, self.y, lr=0.0)


if __name__ == "__main__":
    unittest.main()
