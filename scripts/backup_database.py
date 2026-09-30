#!/usr/bin/env python3
"""Create a verified, private SQLite backup, including committed WAL content.

Usage: python scripts/backup_database.py --source PATH --destination PATH
The destination must not exist. Stdout contains only verification metadata;
errors deliberately omit database contents, SQL and exception details.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import stat
import sys
import tempfile


def table_counts(connection: sqlite3.Connection) -> dict[str, int]:
    names = [row[0] for row in connection.execute(
        "SELECT name FROM sqlite_schema WHERE type = 'table' ORDER BY name"
    )]
    return {
        name: connection.execute('SELECT COUNT(*) FROM "' + name.replace('"', '""') + '"').fetchone()[0]
        for name in names
    }


def verify_integrity(connection: sqlite3.Connection) -> None:
    if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
        raise ValueError("Backup integrity check failed")


def backup_database(source: Path, destination: Path) -> dict:
    source = Path(source).resolve()
    destination = Path(destination).absolute()
    # Never open or unlink the public destination. Only publish a completed
    # private staging inode using an atomic, no-overwrite hard link.
    with tempfile.TemporaryDirectory(prefix=".medhub-backup-", dir=destination.parent) as temporary:
        staged = Path(temporary) / "verified.sqlite"
        # mode=ro preserves a missing source and reads committed WAL normally.
        with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as original:
            # Pin the same read snapshot for both the backup API and row counts.
            original.execute("BEGIN")
            counts = table_counts(original)
            descriptor = os.open(staged, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            try:
                os.fchmod(descriptor, 0o600)
                staged_identity = os.fstat(descriptor)
            finally:
                os.close(descriptor)
            with closing(sqlite3.connect(staged)) as backup:
                original.backup(backup)
                # Produce one independently readable file, not a WAL-dependent set.
                backup.execute("PRAGMA journal_mode=DELETE")
                verify_integrity(backup)
                if table_counts(backup) != counts:
                    raise ValueError("Backup table counts do not match")
            original.rollback()
        current = staged.lstat()
        if (current.st_dev, current.st_ino) != (staged_identity.st_dev, staged_identity.st_ino):
            raise ValueError("Staging identity changed")
        os.link(staged, destination, follow_symlinks=False)
    published = destination.lstat()
    if ((published.st_dev, published.st_ino) != (staged_identity.st_dev, staged_identity.st_ino)
            or not stat.S_ISREG(published.st_mode) or stat.S_IMODE(published.st_mode) != 0o600):
        raise ValueError("Published backup identity or permissions changed")
    return {"verified": True, "integrity_check": "ok", "table_counts": counts}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = backup_database(args.source, args.destination)
    except Exception:
        print("Backup failed; no verified backup was produced.", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
