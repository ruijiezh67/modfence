"""Domain errors."""


class LibraryError(Exception):
    """Base class for all library rule violations."""


class BookNotFound(LibraryError):
    """No book with the given ISBN exists."""


class MemberNotFound(LibraryError):
    """No member with the given id exists."""


class LoanNotFound(LibraryError):
    """No loan with the given id exists."""


class DuplicateEntry(LibraryError):
    """A book or member with the same key already exists."""


class NoCopiesAvailable(LibraryError):
    """Every copy of the book is on loan."""


class LoanLimitReached(LibraryError):
    """The member already holds the maximum number of loans."""


class AlreadyReturned(LibraryError):
    """The loan was already closed."""
