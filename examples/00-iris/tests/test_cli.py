"""Tests for the `python -m iris` command and the end-to-end pipeline."""

import contextlib
import io
import unittest

from iris.cli.main import format_confusion, main, run_pipeline


class PipelineTests(unittest.TestCase):
    """The default pipeline reaches a fixed, high test accuracy."""

    def test_accuracy_on_fixed_split(self):
        """Seed 0 holds out 45 rows and scores at least 0.9 on them."""
        result = run_pipeline()
        self.assertEqual((result["n_train"], result["n_test"]), (105, 45))
        self.assertGreaterEqual(result["accuracy"], 0.9)
        self.assertEqual(sum(map(sum, result["confusion"])), 45)

    def test_reproducible(self):
        """Two runs with the same seed give the same accuracy and losses."""
        a, b = run_pipeline(seed=3, epochs=50), run_pipeline(seed=3, epochs=50)
        self.assertEqual((a["accuracy"], a["losses"]), (b["accuracy"], b["losses"]))


class CommandTests(unittest.TestCase):
    """The command prints a report and uses exit codes properly."""

    def test_train_prints_report(self):
        """`train` exits 0 and prints accuracy and the confusion matrix."""
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main(["train", "--epochs", "50"])
        self.assertEqual(code, 0)
        self.assertIn("test accuracy:", out.getvalue())
        self.assertIn("Iris-virginica", out.getvalue())

    def test_missing_data_file(self):
        """A bad --data path exits 1 with an error on stderr."""
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = main(["train", "--data", "no-such-file.csv"])
        self.assertEqual(code, 1)
        self.assertIn("error:", err.getvalue())

    def test_help(self):
        """--help exits 0 and names the train command."""
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit) as ctx:
            main(["--help"])
        self.assertEqual(ctx.exception.code, 0)
        self.assertIn("train", out.getvalue())

    def test_format_confusion(self):
        """The table has a header line plus one line per class."""
        text = format_confusion([[1, 0], [2, 3]], ["a", "b"])
        self.assertEqual(text.splitlines(), ["   a  b", "a  1  0", "b  2  3"])


if __name__ == "__main__":
    unittest.main()
