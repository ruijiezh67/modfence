"""argparse front end."""

import argparse
import sys
from datetime import date

from library.domain.errors import LibraryError
from library.reports.overdue import overdue_loans
from library.reports.popular import popular_books
from library.services.catalog import CatalogService
from library.services.lending import LendingService
from library.storage.json_repo import JsonRepository


def build_parser() -> argparse.ArgumentParser:
    """Create the argument parser with one subcommand per action."""
    parser = argparse.ArgumentParser(prog="library", description="Library loans")
    parser.add_argument("--data", default="library.json", help="JSON data file")
    parser.add_argument("--today", type=date.fromisoformat, default=None,
                        help="override today's date (YYYY-MM-DD)")
    sub = parser.add_subparsers(dest="command", required=True)

    book = sub.add_parser("add-book", help="add a book")
    book.add_argument("isbn")
    book.add_argument("title")
    book.add_argument("author")
    book.add_argument("--copies", type=int, default=1)

    member = sub.add_parser("add-member", help="add a member")
    member.add_argument("member_id")
    member.add_argument("name")

    lend = sub.add_parser("lend", help="lend a book")
    lend.add_argument("isbn")
    lend.add_argument("member_id")

    ret = sub.add_parser("return", help="return a book")
    ret.add_argument("loan_id", type=int)

    sub.add_parser("overdue", help="list overdue loans")
    popular = sub.add_parser("popular", help="most borrowed books")
    popular.add_argument("--limit", type=int, default=5)
    return parser


def run(args: argparse.Namespace) -> list[str]:
    """Execute the parsed command and return the output lines."""
    repo = JsonRepository(args.data)
    today = args.today or date.today()
    catalog = CatalogService(repo)
    lending = LendingService(repo, today=lambda: today)

    if args.command == "add-book":
        book = catalog.add_book(args.isbn, args.title, args.author, args.copies)
        return [f"added book {book.isbn}: {book.title}"]
    if args.command == "add-member":
        member = catalog.add_member(args.member_id, args.name)
        return [f"added member {member.member_id}: {member.name}"]
    if args.command == "lend":
        loan = lending.lend(args.isbn, args.member_id)
        return [f"loan {loan.loan_id}: due {loan.due_on.isoformat()}"]
    if args.command == "return":
        loan = lending.return_book(args.loan_id)
        return [f"loan {loan.loan_id} returned"]
    if args.command == "overdue":
        rows = overdue_loans(repo, today)
        lines = [f"loan {ln.loan_id} {ln.isbn} {ln.member_id} {d} days" for ln, d in rows]
        return lines or ["no overdue loans"]
    rows = popular_books(repo, args.limit)
    return [f"{count} x {book.title}" for book, count in rows] or ["no loans yet"]


def main(argv: list[str] | None = None) -> int:
    """Entry point; returns a process exit code."""
    args = build_parser().parse_args(argv)
    try:
        lines = run(args)
    except (LibraryError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print("\n".join(lines))
    return 0
