"""Tests for the softmax regression model."""

import math
import unittest

from iris.model.softmax import SoftmaxRegression, softmax


class SoftmaxTests(unittest.TestCase):
    """The softmax function returns a stable probability distribution."""

    def test_sums_to_one(self):
        """Probabilities sum to 1 and keep the order of the scores."""
        p = softmax([1.0, 2.0, 3.0])
        self.assertAlmostEqual(sum(p), 1.0)
        self.assertTrue(p[0] < p[1] < p[2])

    def test_large_scores(self):
        """Huge scores do not overflow."""
        p = softmax([1000.0, 1000.0])
        self.assertEqual(p, [0.5, 0.5])


class ModelTests(unittest.TestCase):
    """Initialisation, prediction and a gradient step behave as specified."""

    X = [[1.0, 0.0], [0.0, 1.0], [-1.0, -1.0]]
    y = [0, 1, 2]

    def test_seeded_init(self):
        """The same seed gives the same weights; biases start at zero."""
        a, b = SoftmaxRegression(4, 3, seed=1), SoftmaxRegression(4, 3, seed=1)
        self.assertEqual(a.weights, b.weights)
        self.assertEqual(a.biases, [0.0, 0.0, 0.0])

    def test_predict_proba_shape(self):
        """One distribution of 3 probabilities per row."""
        probs = SoftmaxRegression(2, 3).predict_proba(self.X)
        self.assertEqual(len(probs), 3)
        for p in probs:
            self.assertEqual(len(p), 3)
            self.assertAlmostEqual(sum(p), 1.0)

    def test_initial_loss_near_uniform(self):
        """With near-zero weights the loss is close to log(3)."""
        self.assertAlmostEqual(SoftmaxRegression(2, 3).loss(self.X, self.y), math.log(3), delta=0.05)

    def test_gradient_matches_finite_difference(self):
        """The analytic gradient of one weight agrees with a numerical estimate."""
        model = SoftmaxRegression(2, 3, seed=3)
        grad_w, _ = model.gradients(self.X, self.y)
        eps = 1e-6
        model.weights[1][0] += eps
        up = model.loss(self.X, self.y)
        model.weights[1][0] -= 2 * eps
        down = model.loss(self.X, self.y)
        self.assertAlmostEqual(grad_w[1][0], (up - down) / (2 * eps), places=5)

    def test_step_lowers_loss(self):
        """One step returns the old loss, and the loss afterwards is lower."""
        model = SoftmaxRegression(2, 3)
        before = model.step(self.X, self.y, lr=0.5)
        self.assertLess(model.loss(self.X, self.y), before)

    def test_predict_returns_class_indices(self):
        """Predictions are class indices in range."""
        preds = SoftmaxRegression(2, 3).predict(self.X)
        self.assertTrue(all(p in (0, 1, 2) for p in preds))


if __name__ == "__main__":
    unittest.main()
