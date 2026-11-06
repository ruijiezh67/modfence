"""Overdue loans report."""

from datetime import date

from library.domain.models import Loan
from library.storage.base import Repository


def overdue_loans(repo: Repository, today: date) -> list[tuple[Loan, int]]:
    """Active loans past their due date as (loan, days overdue), worst first."""
    rows = [
        (loan, loan.days_overdue(today))
        for loan in repo.list_loans()
        if loan.days_overdue(today) > 0
    ]
    return sorted(rows, key=lambda row: (-row[1], row[0].loan_id))
