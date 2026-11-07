"""The `python -m iris` command: load, split, scale, train, evaluate, then print a report."""

import argparse
import sys

from iris.data.load import encode_labels, load_iris
from iris.data.split import train_test_split
from iris.evaluate.metrics import accuracy, confusion_matrix
from iris.features.scale import Standardizer
from iris.model.softmax import SoftmaxRegression
from iris.train.loop import train


def run_pipeline(data_path: str | None = None, test_fraction: float = 0.3, seed: int = 0,
                 epochs: int = 200, lr: float = 0.5) -> dict:
    """Run the whole pipeline once and return its results as a dict."""
    rows, labels = load_iris(data_path)
    y, classes = encode_labels(labels)
    X_train, X_test, y_train, y_test = train_test_split(rows, y, test_fraction, seed)
    scaler = Standardizer().fit(X_train)
    X_train, X_test = scaler.transform(X_train), scaler.transform(X_test)
    model = SoftmaxRegression(len(X_train[0]), len(classes), seed=seed)
    losses = train(model, X_train, y_train, epochs=epochs, lr=lr)
    y_pred = model.predict(X_test)
    return {
        "classes": classes,
        "n_train": len(y_train),
        "n_test": len(y_test),
        "losses": losses,
        "accuracy": accuracy(y_test, y_pred),
        "confusion": confusion_matrix(y_test, y_pred, len(classes)),
    }


def format_confusion(matrix: list[list[int]], classes: list[str]) -> str:
    """Render a confusion matrix as a text table (rows = true class, columns = predicted)."""
    width = max(len(c) for c in classes)
    lines = [" " * width + "  " + "  ".join(c.rjust(width) for c in classes)]
    for name, row in zip(classes, matrix):
        lines.append(name.rjust(width) + "  " + "  ".join(str(v).rjust(width) for v in row))
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    """Define the command-line arguments."""
    parser = argparse.ArgumentParser(
        prog="python -m iris",
        description="Train and evaluate a softmax classifier on the Iris dataset.")
    sub = parser.add_subparsers(dest="command", required=True)
    t = sub.add_parser("train", help="train on a stratified split and report test accuracy")
    t.add_argument("--data", default=None, help="path to iris.csv (default: the bundled copy)")
    t.add_argument("--test-fraction", type=float, default=0.3, help="share of each class held out (default 0.3)")
    t.add_argument("--seed", type=int, default=0, help="seed for the split and the weight init (default 0)")
    t.add_argument("--epochs", type=int, default=200, help="gradient descent steps (default 200)")
    t.add_argument("--lr", type=float, default=0.5, help="learning rate (default 0.5)")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Parse argv, run the requested command and print its report; return the exit code."""
    args = build_parser().parse_args(sys.argv[1:] if argv is None else argv)
    try:
        result = run_pipeline(args.data, args.test_fraction, args.seed, args.epochs, args.lr)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    losses = result["losses"]
    print(f"train rows: {result['n_train']}  test rows: {result['n_test']}")
    print(f"loss: {losses[0]:.4f} -> {losses[-1]:.4f} over {len(losses)} epochs")
    print(f"test accuracy: {result['accuracy']:.4f}")
    print("confusion matrix (rows = true class, columns = predicted):")
    print(format_confusion(result["confusion"], result["classes"]))
    return 0
