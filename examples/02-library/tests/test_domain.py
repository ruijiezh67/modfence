import unittest
from datetime import date

from library.domain.models import Loan


class LoanTests(unittest.TestCase):
    def make(self, returned_on=None):
        return Loan(1, "isbn", "m1", date(2026, 1, 1), date(2026, 1, 15), returned_on)

    def test_active(self):
        self.assertTrue(self.make().is_active)
        self.assertFalse(self.make(date(2026, 1, 10)).is_active)

    def test_days_overdue(self):
        loan = self.make()
        self.assertEqual(loan.days_overdue(date(2026, 1, 15)), 0)
        self.assertEqual(loan.days_overdue(date(2026, 1, 20)), 5)

    def test_returned_loan_is_never_overdue(self):
        self.assertEqual(self.make(date(2026, 1, 10)).days_overdue(date(2026, 3, 1)), 0)


if __name__ == "__main__":
    unittest.main()
