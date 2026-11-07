"""Tests for the Standardizer."""

import unittest

from iris.features.scale import Standardizer


class StandardizerTests(unittest.TestCase):
    """Fit learns statistics from its input only; transform reuses them."""

    def test_fit_transform_centres_and_scales(self):
        """Each fitted column ends with mean 0 and population standard deviation 1."""
        X = [[1.0, 10.0], [2.0, 20.0], [3.0, 30.0], [4.0, 40.0]]
        Z = Standardizer().fit_transform(X)
        for j in range(2):
            col = [row[j] for row in Z]
            mean = sum(col) / len(col)
            var = sum((v - mean) ** 2 for v in col) / len(col)
            self.assertAlmostEqual(mean, 0.0)
            self.assertAlmostEqual(var, 1.0)

    def test_uses_train_stats_only(self):
        """Transforming test rows uses the training mean and std, not the test rows' own."""
        scaler = Standardizer().fit([[0.0], [2.0]])  # mean 1, std 1
        self.assertEqual(scaler.transform([[101.0], [103.0]]), [[100.0], [102.0]])
        self.assertEqual(scaler.means, [1.0])
        self.assertEqual(scaler.stds, [1.0])

    def test_constant_column(self):
        """A constant column does not divide by zero."""
        self.assertEqual(Standardizer().fit_transform([[5.0], [5.0]]), [[0.0], [0.0]])

    def test_transform_before_fit(self):
        """Transform on an unfitted scaler raises."""
        with self.assertRaises(RuntimeError):
            Standardizer().transform([[1.0]])


if __name__ == "__main__":
    unittest.main()
