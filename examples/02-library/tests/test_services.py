import unittest
from datetime import date

from library.domain.errors import (
    AlreadyReturned,
    BookNotFound,
    DuplicateEntry,
    LoanLimitReached,
    MemberNotFound,
    NoCopiesAvailable,
)
from library.services.catalog import CatalogService
from library.services.lending import LendingService
from library.storage.memory import MemoryRepository


class LendingTests(unittest.TestCase):
    def setUp(self):
        self.repo = MemoryRepository()
        self.today = date(2026, 3, 1)
        self.catalog = CatalogService(self.repo)
        self.lending = LendingService(self.repo, today=lambda: self.today)
        self.catalog.add_member("m1", "Ada")
        self.catalog.add_member("m2", "Bob")
        for n in range(1, 5):
            self.catalog.add_book(f"b{n}", f"Book {n}", "Author")

    def test_lend_sets_due_date(self):
        loan = self.lending.lend("b1", "m1")
        self.assertEqual(loan.due_on, date(2026, 3, 15))

    def test_unknown_member_and_book(self):
        with self.assertRaises(MemberNotFound):
            self.lending.lend("b1", "nobody")
        with self.assertRaises(BookNotFound):
            self.lending.lend("nope", "m1")

    def test_no_copies_left(self):
        self.lending.lend("b1", "m1")
        with self.assertRaises(NoCopiesAvailable):
            self.lending.lend("b1", "m2")

    def test_loan_limit(self):
        for isbn in ("b1", "b2", "b3"):
            self.lending.lend(isbn, "m1")
        with self.assertRaises(LoanLimitReached):
            self.lending.lend("b4", "m1")

    def test_return_frees_a_copy(self):
        loan = self.lending.lend("b1", "m1")
        self.lending.return_book(loan.loan_id)
        self.assertEqual(self.lending.copies_available("b1"), 1)
        with self.assertRaises(AlreadyReturned):
            self.lending.return_book(loan.loan_id)

    def test_duplicates_rejected(self):
        with self.assertRaises(DuplicateEntry):
            self.catalog.add_book("b1", "Again", "Author")
        with self.assertRaises(DuplicateEntry):
            self.catalog.add_member("m1", "Ada")


if __name__ == "__main__":
    unittest.main()
