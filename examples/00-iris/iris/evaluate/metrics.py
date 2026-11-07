"""Classification metrics: accuracy and the confusion matrix."""


def accuracy(y_true: list[int], y_pred: list[int]) -> float:
    """Fraction of predictions that equal the true label."""
    if len(y_true) != len(y_pred):
        raise ValueError("y_true and y_pred must have the same length")
    if not y_true:
        raise ValueError("cannot score an empty prediction list")
    return sum(t == p for t, p in zip(y_true, y_pred)) / len(y_true)


def confusion_matrix(y_true: list[int], y_pred: list[int], n_classes: int) -> list[list[int]]:
    """Count table where cell [i][j] is the number of rows of true class i predicted as class j."""
    if len(y_true) != len(y_pred):
        raise ValueError("y_true and y_pred must have the same length")
    matrix = [[0] * n_classes for _ in range(n_classes)]
    for t, p in zip(y_true, y_pred):
        matrix[t][p] += 1
    return matrix
