"""The repository interface every storage backend implements."""

from abc import ABC, abstractmethod

from library.domain.models import Book, Loan, Member


class Repository(ABC):
    """Persistence operations the services layer relies on."""

    @abstractmethod
    def add_book(self, book: Book) -> None:
        """Store a new book."""

    @abstractmethod
    def get_book(self, isbn: str) -> Book | None:
        """Return the book, or None."""

    @abstractmethod
    def list_books(self) -> list[Book]:
        """Return all books."""

    @abstractmethod
    def add_member(self, member: Member) -> None:
        """Store a new member."""

    @abstractmethod
    def get_member(self, member_id: str) -> Member | None:
        """Return the member, or None."""

    @abstractmethod
    def list_members(self) -> list[Member]:
        """Return all members."""

    @abstractmethod
    def add_loan(self, loan: Loan) -> None:
        """Store a new loan."""

    @abstractmethod
    def update_loan(self, loan: Loan) -> None:
        """Persist changes to an existing loan."""

    @abstractmethod
    def get_loan(self, loan_id: int) -> Loan | None:
        """Return the loan, or None."""

    @abstractmethod
    def list_loans(self) -> list[Loan]:
        """Return all loans, active and closed."""

    def next_loan_id(self) -> int:
        """Return an unused loan id."""
        return max((loan.loan_id for loan in self.list_loans()), default=0) + 1
