"""Lending and returning books."""

from collections.abc import Callable
from datetime import date

from library.domain.errors import (
    AlreadyReturned,
    BookNotFound,
    LoanLimitReached,
    LoanNotFound,
    MemberNotFound,
    NoCopiesAvailable,
)
from library.domain.models import Loan
from library.services.rules import MAX_LOANS_PER_MEMBER, due_date
from library.storage.base import Repository


class LendingService:
    """Applies the lending rules and records loans."""

    def __init__(
        self,
        repo: Repository,
        today: Callable[[], date] = date.today,
        max_loans: int = MAX_LOANS_PER_MEMBER,
    ) -> None:
        self._repo = repo
        self._today = today
        self._max_loans = max_loans

    def active_loans_of(self, member_id: str) -> list[Loan]:
        """Loans the member has not returned yet."""
        return [
            loan
            for loan in self._repo.list_loans()
            if loan.member_id == member_id and loan.is_active
        ]

    def copies_available(self, isbn: str) -> int:
        """Copies of the book not currently on loan."""
        book = self._repo.get_book(isbn)
        if book is None:
            raise BookNotFound(isbn)
        on_loan = sum(
            1 for loan in self._repo.list_loans() if loan.isbn == isbn and loan.is_active
        )
        return book.copies - on_loan

    def lend(self, isbn: str, member_id: str) -> Loan:
        """Lend a book to a member, enforcing copies and the loan limit."""
        if self._repo.get_member(member_id) is None:
            raise MemberNotFound(member_id)
        if self.copies_available(isbn) <= 0:
            raise NoCopiesAvailable(isbn)
        if len(self.active_loans_of(member_id)) >= self._max_loans:
            raise LoanLimitReached(f"{member_id} already has {self._max_loans} loans")
        today = self._today()
        loan = Loan(self._repo.next_loan_id(), isbn, member_id, today, due_date(today))
        self._repo.add_loan(loan)
        return loan

    def return_book(self, loan_id: int) -> Loan:
        """Close a loan."""
        loan = self._repo.get_loan(loan_id)
        if loan is None:
            raise LoanNotFound(str(loan_id))
        if not loan.is_active:
            raise AlreadyReturned(str(loan_id))
        loan.returned_on = self._today()
        self._repo.update_loan(loan)
        return loan
