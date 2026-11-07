"""Tests for accuracy and the confusion matrix."""

import unittest

from iris.evaluate.metrics import accuracy, confusion_matrix


class MetricsTests(unittest.TestCase):
    """Metrics count correctly on small hand-checked examples."""

    def test_accuracy(self):
        """3 of 4 correct is 0.75."""
        self.assertEqual(accuracy([0, 1, 2, 2], [0, 1, 1, 2]), 0.75)

    def test_accuracy_errors(self):
        """Mismatched or empty inputs raise."""
        with self.assertRaises(ValueError):
            accuracy([0, 1], [0])
        with self.assertRaises(ValueError):
            accuracy([], [])

    def test_confusion_matrix(self):
        """Rows are true classes, columns predicted, and the cells sum to the row count."""
        m = confusion_matrix([0, 1, 2, 2], [0, 1, 1, 2], 3)
        self.assertEqual(m, [[1, 0, 0], [0, 1, 0], [0, 1, 1]])
        self.assertEqual(sum(map(sum, m)), 4)

    def test_diagonal_matches_accuracy(self):
        """The diagonal of the matrix over the total equals the accuracy."""
        y_true, y_pred = [0, 0, 1, 1, 2, 2], [0, 1, 1, 1, 2, 0]
        m = confusion_matrix(y_true, y_pred, 3)
        self.assertAlmostEqual(sum(m[i][i] for i in range(3)) / len(y_true), accuracy(y_true, y_pred))


if __name__ == "__main__":
    unittest.main()
