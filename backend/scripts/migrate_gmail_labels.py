"""Dry-run or apply the one-time managed Gmail label migration."""

import argparse
import json

from app.db.session import SessionLocal
from app.services.gmail_label_migration import migrate_managed_gmail_labels


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply label changes. Without this flag the command is read-only.",
    )
    parser.add_argument("--connection-id", type=int, help="Limit the migration to one connection.")
    args = parser.parse_args()
    with SessionLocal() as db:
        result = migrate_managed_gmail_labels(
            db,
            dry_run=not args.apply,
            connection_id=args.connection_id,
        )
    print(json.dumps(result.as_dict(), indent=2, sort_keys=True))
    return 1 if result.failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
