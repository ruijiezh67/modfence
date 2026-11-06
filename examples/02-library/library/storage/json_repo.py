"""JSON-file repository: the memory repository plus load and save."""

import json
from dataclasses import asdict
from datetime import date
from pathlib import Path

from library.domain.models import Book, Loan, Member
from library.storage.memory import MemoryRepository

_DATE_FIELDS = ("loaned_on", "due_on", "returned_on")


class JsonRepository(MemoryRepository):
    """Loads the file on creation and rewrites it after every change."""

    def __init__(self, path: str | Path) -> None:
        super().__init__()
        self._path = Path(path)
        if self._path.exists():
            self._load()

    def _load(self) -> None:
        data = json.loads(self._path.read_text(encoding="utf-8"))
        for item in data.get("books", []):
            super().add_book(Book(**item))
        for item in data.get("members", []):
            super().add_member(Member(**item))
        for item in data.get("loans", []):
            for key in _DATE_FIELDS:
                item[key] = date.fromisoformat(item[key]) if item[key] else None
            super().add_loan(Loan(**item))

    def _save(self) -> None:
        loans = []
        for loan in self.list_loans():
            row = asdict(loan)
            for key in _DATE_FIELDS:
                row[key] = row[key].isoformat() if row[key] else None
            loans.append(row)
        data = {
            "books": [asdict(b) for b in self.list_books()],
            "members": [asdict(m) for m in self.list_members()],
            "loans": loans,
        }
        self._path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def add_book(self, book: Book) -> None:
        super().add_book(book)
        self._save()

    def add_member(self, member: Member) -> None:
        super().add_member(member)
        self._save()

    def add_loan(self, loan: Loan) -> None:
        super().add_loan(loan)
        self._save()

    def update_loan(self, loan: Loan) -> None:
        super().update_loan(loan)
        self._save()
