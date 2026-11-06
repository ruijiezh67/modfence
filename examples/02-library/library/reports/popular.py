"""Most borrowed books report."""

from collections import Counter

from library.domain.models import Book
from library.storage.base import Repository


def popular_books(repo: Repository, limit: int = 5) -> list[tuple[Book, int]]:
    """Books ranked by total number of loans, ties broken by title."""
    counts = Counter(loan.isbn for loan in repo.list_loans())
    rows = [(book, counts[book.isbn]) for book in repo.list_books() if counts[book.isbn]]
    rows.sort(key=lambda row: (-row[1], row[0].title))
    return rows[:limit]
