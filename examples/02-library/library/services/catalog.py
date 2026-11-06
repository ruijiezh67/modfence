"""Adding books and members."""

from library.domain.errors import DuplicateEntry
from library.domain.models import Book, Member
from library.storage.base import Repository


class CatalogService:
    """Registers books and members, rejecting duplicates."""

    def __init__(self, repo: Repository) -> None:
        self._repo = repo

    def add_book(self, isbn: str, title: str, author: str, copies: int = 1) -> Book:
        """Add a book; ``copies`` must be at least 1."""
        if self._repo.get_book(isbn):
            raise DuplicateEntry(f"book {isbn} already exists")
        if copies < 1:
            raise ValueError("copies must be at least 1")
        book = Book(isbn, title, author, copies)
        self._repo.add_book(book)
        return book

    def add_member(self, member_id: str, name: str) -> Member:
        """Add a member."""
        if self._repo.get_member(member_id):
            raise DuplicateEntry(f"member {member_id} already exists")
        member = Member(member_id, name)
        self._repo.add_member(member)
        return member
