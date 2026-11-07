"""Tests for loading the Iris CSV and the stratified split."""

import unittest
from collections import Counter

from iris.data.load import FEATURE_NAMES, encode_labels, load_iris
from iris.data.split import train_test_split


class LoadTests(unittest.TestCase):
    """The bundled CSV loads as 150 rows of 4 floats in 3 balanced classes."""

    def test_shape(self):
        """150 rows, 4 numeric features each."""
        rows, labels = load_iris()
        self.assertEqual(len(rows), 150)
        self.assertEqual(len(labels), 150)
        self.assertEqual(len(FEATURE_NAMES), 4)
        self.assertTrue(all(len(r) == 4 and all(isinstance(v, float) for v in r) for r in rows))

    def test_classes_balanced(self):
        """Exactly 50 rows per species."""
        _, labels = load_iris()
        self.assertEqual(Counter(labels),
                         {"Iris-setosa": 50, "Iris-versicolor": 50, "Iris-virginica": 50})

    def test_first_row(self):
        """The first row matches the UCI file."""
        rows, labels = load_iris()
        self.assertEqual((rows[0], labels[0]), ([5.1, 3.5, 1.4, 0.2], "Iris-setosa"))

    def test_encode_labels(self):
        """Labels map to 0..k-1 in sorted class order."""
        codes, classes = encode_labels(["b", "a", "b", "c"])
        self.assertEqual(classes, ["a", "b", "c"])
        self.assertEqual(codes, [1, 0, 1, 2])


class SplitTests(unittest.TestCase):
    """The split is stratified, disjoint, complete and reproducible."""

    def setUp(self):
        """Load and encode the dataset once per test."""
        rows, labels = load_iris()
        self.X = rows
        self.y, _ = encode_labels(labels)

    def test_stratified(self):
        """Each class contributes 15 of its 50 rows to a 30% test set."""
        _, _, y_train, y_test = train_test_split(self.X, self.y, 0.3, seed=0)
        self.assertEqual(Counter(y_test), {0: 15, 1: 15, 2: 15})
        self.assertEqual(Counter(y_train), {0: 35, 1: 35, 2: 35})

    def test_disjoint_and_complete(self):
        """Train and test rows together are exactly the original rows."""
        X_train, X_test, _, _ = train_test_split(self.X, self.y, 0.3, seed=0)
        self.assertEqual(sorted(map(tuple, X_train + X_test)), sorted(map(tuple, self.X)))

    def test_reproducible(self):
        """The same seed gives the same split; a different seed gives a different one."""
        a = train_test_split(self.X, self.y, 0.3, seed=7)
        b = train_test_split(self.X, self.y, 0.3, seed=7)
        c = train_test_split(self.X, self.y, 0.3, seed=8)
        self.assertEqual(a, b)
        self.assertNotEqual(a[1], c[1])

    def test_bad_fraction(self):
        """A test fraction outside (0, 1) is rejected."""
        with self.assertRaises(ValueError):
            train_test_split(self.X, self.y, 1.0)


if __name__ == "__main__":
    unittest.main()
