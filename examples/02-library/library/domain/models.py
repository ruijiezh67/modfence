"""Entities of the library."""

from dataclasses import dataclass
from datetime import date


@dataclass
class Book:
    """A title the library owns, with a number of physical copies."""

    isbn: str
    title: str
    author: str
    copies: int = 1


@dataclass
class Member:
    """A person who may borrow books."""

    member_id: str
    name: str


@dataclass
class Loan:
    """One book borrowed by one member."""

    loan_id: int
    isbn: str
    member_id: str
    loaned_on: date
    due_on: date
    returned_on: date | None = None

    @property
    def is_active(self) -> bool:
        """True while the book has not been returned."""
        return self.returned_on is None

    def days_overdue(self, today: date) -> int:
        """Days past the due date, or 0 if not overdue or already returned."""
        if not self.is_active:
            return 0
        return max((today - self.due_on).days, 0)
