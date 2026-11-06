import unittest
from datetime import date

from library.reports.overdue import overdue_loans
from library.reports.popular import popular_books
from library.services.catalog import CatalogService
from library.services.lending import LendingService
from library.storage.memory import MemoryRepository


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.repo = MemoryRepository()
        self.day = date(2026, 3, 1)
        catalog = CatalogService(self.repo)
        self.lending = LendingService(self.repo, today=lambda: self.day)
        catalog.add_member("m1", "Ada")
        catalog.add_book("b1", "Alpha", "X", copies=3)
        catalog.add_book("b2", "Beta", "X", copies=3)
        catalog.add_book("b3", "Gamma", "X")

    def test_overdue_sorted_worst_first(self):
        self.lending.lend("b1", "m1")
        self.day = date(2026, 3, 5)
        self.lending.lend("b2", "m1")
        rows = overdue_loans(self.repo, date(2026, 3, 25))
        self.assertEqual([(loan.isbn, days) for loan, days in rows], [("b1", 10), ("b2", 6)])

    def test_returned_loans_not_overdue(self):
        loan = self.lending.lend("b1", "m1")
        self.lending.return_book(loan.loan_id)
        self.assertEqual(overdue_loans(self.repo, date(2027, 1, 1)), [])

    def test_popular_books(self):
        for _ in range(2):
            loan = self.lending.lend("b2", "m1")
            self.lending.return_book(loan.loan_id)
        self.lending.lend("b1", "m1")
        rows = popular_books(self.repo)
        self.assertEqual([(b.isbn, n) for b, n in rows], [("b2", 2), ("b1", 1)])
        self.assertEqual(len(popular_books(self.repo, limit=1)), 1)


if __name__ == "__main__":
    unittest.main()
