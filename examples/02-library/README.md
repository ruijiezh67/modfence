# 02-library

A library-loans system built in layers. Books, members and loans are plain dataclasses. A repository interface hides where data is kept (memory or a JSON file). Services enforce the lending rules (copies available, three loans per member, 14-day loan period). Reports read the stored data, and an argparse CLI sits on top. It has no reservations, no late fines and no search yet.

| Module | Responsibility | Depends on |
|---|---|---|
| `library.domain` | Book, Member, Loan dataclasses and domain errors | none |
| `library.storage` | Repository interface, in-memory and JSON-file implementations | `domain` |
| `library.services` | Catalog management, lending and returning, lending rules | `domain`, `storage` |
| `library.reports` | Overdue loans and popular books | `domain`, `storage` |
| `library.cli` | argparse subcommands wiring everything together | `domain`, `services`, `reports`, `storage` |

## Run

```
python -m library --data lib.json add-book 978-0 "Dune" "Frank Herbert" --copies 2
python -m library --data lib.json add-member m1 "Ada"
python -m library --data lib.json lend 978-0 m1
python -m library --data lib.json overdue
python -m library --data lib.json popular
python -m library --data lib.json return 1
```

Use the global `--today YYYY-MM-DD` option to simulate a different date.

## Test

```
python -m unittest discover -s tests -t .
```

Python 3.10+, standard library only.
