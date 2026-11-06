import tempfile
import unittest
from datetime import date
from pathlib import Path

from library.domain.models import Book, Loan, Member
from library.storage.json_repo import JsonRepository
from library.storage.memory import MemoryRepository


class MemoryRepositoryTests(unittest.TestCase):
    def test_round_trip(self):
        repo = MemoryRepository()
        repo.add_book(Book("1", "Dune", "Herbert", 2))
        repo.add_member(Member("m1", "Ada"))
        self.assertEqual(repo.get_book("1").title, "Dune")
        self.assertEqual(repo.get_member("m1").name, "Ada")
        self.assertIsNone(repo.get_book("missing"))

    def test_next_loan_id(self):
        repo = MemoryRepository()
        self.assertEqual(repo.next_loan_id(), 1)
        repo.add_loan(Loan(7, "1", "m1", date(2026, 1, 1), date(2026, 1, 15)))
        self.assertEqual(repo.next_loan_id(), 8)


class JsonRepositoryTests(unittest.TestCase):
    def test_persists_between_instances(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "data.json"
            repo = JsonRepository(path)
            repo.add_book(Book("1", "Dune", "Herbert"))
            repo.add_member(Member("m1", "Ada"))
            loan = Loan(1, "1", "m1", date(2026, 1, 1), date(2026, 1, 15))
            repo.add_loan(loan)
            loan.returned_on = date(2026, 1, 9)
            repo.update_loan(loan)

            again = JsonRepository(path)
            self.assertEqual(again.get_book("1").author, "Herbert")
            self.assertEqual(again.get_loan(1).returned_on, date(2026, 1, 9))
            self.assertEqual(again.get_loan(1).due_on, date(2026, 1, 15))


if __name__ == "__main__":
    unittest.main()
