"""Read the Iris CSV into numeric feature rows and string labels."""

import csv
import os

FEATURE_NAMES = ["sepal_length", "sepal_width", "petal_length", "petal_width"]
LABEL_NAME = "species"
DEFAULT_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "data", "iris.csv")


def load_iris(path: str | None = None) -> tuple[list[list[float]], list[str]]:
    """Return (rows of 4 floats, species labels) read from the Iris CSV."""
    rows, labels = [], []
    with open(path or DEFAULT_PATH, newline="", encoding="utf-8") as f:
        for record in csv.DictReader(f):
            rows.append([float(record[name]) for name in FEATURE_NAMES])
            labels.append(record[LABEL_NAME])
    return rows, labels


def encode_labels(labels: list[str]) -> tuple[list[int], list[str]]:
    """Map string labels to integers 0..k-1; return (codes, sorted class names)."""
    classes = sorted(set(labels))
    index = {name: i for i, name in enumerate(classes)}
    return [index[name] for name in labels], classes
