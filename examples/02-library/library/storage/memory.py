"""In-memory repository, used by tests and as the base of the JSON one."""

from library.domain.models import Book, Loan, Member
from library.storage.base import Repository


class MemoryRepository(Repository):
    """Keeps everything in dictionaries."""

    def __init__(self) -> None:
        self._books: dict[str, Book] = {}
        self._members: dict[str, Member] = {}
        self._loans: dict[int, Loan] = {}

    def add_book(self, book: Book) -> None:
        self._books[book.isbn] = book

    def get_book(self, isbn: str) -> Book | None:
        return self._books.get(isbn)

    def list_books(self) -> list[Book]:
        return list(self._books.values())

    def add_member(self, member: Member) -> None:
        self._members[member.member_id] = member

    def get_member(self, member_id: str) -> Member | None:
        return self._members.get(member_id)

    def list_members(self) -> list[Member]:
        return list(self._members.values())

    def add_loan(self, loan: Loan) -> None:
        self._loans[loan.loan_id] = loan

    def update_loan(self, loan: Loan) -> None:
        self._loans[loan.loan_id] = loan

    def get_loan(self, loan_id: int) -> Loan | None:
        return self._loans.get(loan_id)

    def list_loans(self) -> list[Loan]:
        return list(self._loans.values())
