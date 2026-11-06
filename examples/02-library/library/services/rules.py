"""Lending policy constants and helpers."""

from datetime import date, timedelta

MAX_LOANS_PER_MEMBER = 3
LOAN_PERIOD_DAYS = 14


def due_date(loaned_on: date) -> date:
    """The date a loan started on ``loaned_on`` must be returned by."""
    return loaned_on + timedelta(days=LOAN_PERIOD_DAYS)
