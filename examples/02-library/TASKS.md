# Tasks for 02-library

Each task lists its target module(s). Acceptance examples can be turned into unit tests directly.

## 1. Configurable loan period (single module: `services`)

Target: `library.services` only (`rules` and `lending`).

Build: let `LendingService` take a `loan_days` argument (default 14) that replaces the module constant, and make `due_date` accept the number of days.

Acceptance:
- `LendingService(repo, today=lambda: date(2026, 3, 1), loan_days=7).lend("b1", "m1").due_on == date(2026, 3, 8)`
- With no argument, the due date is still `date(2026, 3, 15)`
- `LendingService(repo, loan_days=0)` raises `ValueError`

## 2. Books per author report (single module: `reports`)

Target: `library.reports` only (new file `authors.py`).

Build: `books_by_author(repo) -> dict[str, list[str]]` mapping each author to the sorted titles of their books, with authors sorted alphabetically.

Acceptance:
- Books `("1", "Dune", "Herbert")`, `("2", "Children of Dune", "Herbert")`, `("3", "Emma", "Austen")` give `{"Austen": ["Emma"], "Herbert": ["Children of Dune", "Dune"]}` with keys in that order
- An empty repository gives `{}`

## 3. Member loan history (single module: `reports`)

Target: `library.reports` only (new file `history.py`).

Build: `loan_history(repo, member_id, today)` returns one line per loan of that member, newest first, formatted as `"<title> | <loaned_on> | returned <date>"`, `"<title> | <loaned_on> | due <date>"` or `"<title> | <loaned_on> | OVERDUE <n> days"`.

Acceptance:
- A loan of "Dune" on 2026-03-01, returned 2026-03-10 gives `"Dune | 2026-03-01 | returned 2026-03-10"`
- An active loan due 2026-03-15 viewed on 2026-03-10 gives `"... | due 2026-03-15"`
- The same loan viewed on 2026-03-20 gives `"... | OVERDUE 5 days"`
- An unknown member returns an empty list

## 4. Late fines (crosses modules: `domain`, `services`, `storage`, `cli`)

Target: `library.domain`, `library.services`, `library.storage`, `library.cli`.

Build: returning a book after its due date creates a fine of 0.25 per overdue day, capped at 10.00. A member with unpaid fines of 5.00 or more cannot borrow. Domain: a `fine` field on `Loan` and a `FinesOutstanding` error. Services: compute the fine in `return_book`, check it in `lend`. Storage: persist the new field in the JSON repository (files without it must still load). CLI: `return` prints the fine, and a new `pay LOAN_ID` command clears it.

Acceptance:
- Returning a loan 10 days late prints `loan 1 returned, fine 2.50`
- Returning 100 days late gives a fine of `10.00`
- Returning on or before the due date gives a fine of `0.00`
- A member with two unpaid fines of 2.50 gets `FinesOutstanding` when lending
- After `pay 1` and `pay 2`, lending works again
- A JSON file written before this change loads with `fine == 0`

## 5. Reservations (crosses modules: `domain`, `storage`, `services`, `reports`, `cli`)

Target: `library.domain`, `library.storage`, `library.services`, `library.reports`, `library.cli`.

Build: when no copy is available, a member can reserve a book. Reservations form a first-in-first-out queue per book. When a copy is returned, the first member in the queue holds it for 3 days; only that member can borrow it during that window. Domain: `Reservation` dataclass and `ReservationError`s. Storage: add reservation methods to the `Repository` interface and both implementations. Services: a `ReservationService`, and `LendingService.lend` must respect held copies. Reports: a `reservation_queue` report. CLI: `reserve ISBN MEMBER_ID` and `queue ISBN`.

Acceptance:
- Book `b1` with one copy is lent to `m1`. `reserve b1 m2` succeeds and `queue b1` prints `1. m2`
- `reserve b1 m2` a second time raises a duplicate-reservation error
- `reserve b1 m3` gives position 2
- After `m1` returns `b1`, `lend b1 m3` raises `NoCopiesAvailable` (held for `m2`)
- `lend b1 m2` succeeds and `queue b1` then prints `1. m3`
- Three days after the return, an unclaimed hold expires and `m3` may borrow
- Reserving a book that has a free copy raises an error saying to borrow it instead
