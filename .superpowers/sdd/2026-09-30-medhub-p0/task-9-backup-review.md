# Backup subtask review package

New files only; no user backup/deploy performed.

## scripts/backup_database.py
```diff
--- before/scripts/backup_database.py
+++ after/scripts/backup_database.py
@@ -0,0 +1,88 @@
+#!/usr/bin/env python3
+"""Create a verified, private SQLite backup, including committed WAL content.
+
+Usage: python scripts/backup_database.py --source PATH --destination PATH
+The destination must not exist. Stdout contains only verification metadata;
+errors deliberately omit database contents, SQL and exception details.
+"""
+from __future__ import annotations
+
+import argparse
+from contextlib import closing
+import json
+import os
+from pathlib import Path
+import sqlite3
+import sys
+
+
+def table_counts(connection: sqlite3.Connection) -> dict[str, int]:
+    names = [row[0] for row in connection.execute(
+        "SELECT name FROM sqlite_schema WHERE type = 'table' ORDER BY name"
+    )]
+    return {
+        name: connection.execute('SELECT COUNT(*) FROM "' + name.replace('"', '""') + '"').fetchone()[0]
+        for name in names
+    }
+
+
+def verify_integrity(connection: sqlite3.Connection) -> None:
+    if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
+        raise ValueError("Backup integrity check failed")
+
+
+def backup_database(source: Path, destination: Path) -> dict:
+    source = Path(source).resolve()
+    destination = Path(destination).absolute()
+    created_stat = None
+    verified = False
+    try:
+        # mode=ro preserves a missing source and reads committed WAL normally.
+        with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as original:
+            # Pin the same read snapshot for both the backup API and row counts.
+            original.execute("BEGIN")
+            counts = table_counts(original)
+            descriptor = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
+            try:
+                created_stat = os.fstat(descriptor)
+                os.fchmod(descriptor, 0o600)
+            finally:
+                os.close(descriptor)
+            with closing(sqlite3.connect(destination)) as backup:
+                original.backup(backup)
+                # Produce one independently readable file, not a WAL-dependent set.
+                backup.execute("PRAGMA journal_mode=DELETE")
+                verify_integrity(backup)
+                if table_counts(backup) != counts:
+                    raise ValueError("Backup table counts do not match")
+            original.rollback()
+        verified = True
+        return {"verified": True, "integrity_check": "ok", "table_counts": counts}
+    finally:
+        if not verified and created_stat is not None:
+            # Remove only the incomplete file created by this invocation. Never
+            # unlink an existing destination or a path someone has replaced.
+            try:
+                current = destination.lstat()
+                if (current.st_dev, current.st_ino) == (created_stat.st_dev, created_stat.st_ino):
+                    destination.unlink()
+            except FileNotFoundError:
+                pass
+
+
+def main(argv: list[str] | None = None) -> int:
+    parser = argparse.ArgumentParser(description=__doc__)
+    parser.add_argument("--source", type=Path, required=True)
+    parser.add_argument("--destination", type=Path, required=True)
+    args = parser.parse_args(argv)
+    try:
+        result = backup_database(args.source, args.destination)
+    except Exception:
+        print("Backup failed; no verified backup was produced.", file=sys.stderr)
+        return 1
+    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
+    return 0
+
+
+if __name__ == "__main__":
+    raise SystemExit(main())

```

## backend/tests/test_backup_database.py
```diff
--- before/backend/tests/test_backup_database.py
+++ after/backend/tests/test_backup_database.py
@@ -0,0 +1,158 @@
+import importlib.util
+import json
+from pathlib import Path
+import sqlite3
+import subprocess
+import sys
+
+import pytest
+
+
+SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "backup_database.py"
+PRIVATE_TEXT = "SYNTHETIC-PRIVATE-CONSULTATION-DO-NOT-PRINT"
+
+
+def run_backup(source, destination):
+    return subprocess.run([sys.executable, str(SCRIPT), "--source", str(source), "--destination", str(destination)],
+                          capture_output=True, text=True, timeout=20)
+
+
+def seed(path):
+    connection = sqlite3.connect(path)
+    connection.execute("PRAGMA journal_mode=WAL")
+    connection.execute("CREATE TABLE consultations (id INTEGER PRIMARY KEY, clinical_text TEXT)")
+    connection.execute('CREATE TABLE "odd table""name" (value TEXT)')
+    connection.execute("INSERT INTO consultations(clinical_text) VALUES (?)", (PRIVATE_TEXT,))
+    connection.execute('INSERT INTO "odd table""name" VALUES (?)', (PRIVATE_TEXT,))
+    connection.commit()
+    return connection
+
+
+def test_backup_preserves_wal_data_source_and_restricts_permissions(tmp_path):
+    source = tmp_path / "source.sqlite"
+    destination = tmp_path / "backup.sqlite"
+    connection = seed(source)
+    try:
+        assert Path(str(source) + "-wal").is_file()
+        original_bytes = source.read_bytes()
+        result = run_backup(source, destination)
+        assert result.returncode == 0, result.stderr
+        summary = json.loads(result.stdout)
+        assert summary == {"verified": True, "integrity_check": "ok", "table_counts": {"consultations": 1, 'odd table"name': 1}}
+        assert PRIVATE_TEXT not in result.stdout + result.stderr
+        assert source.read_bytes() == original_bytes
+        assert connection.execute("SELECT clinical_text FROM consultations").fetchone()[0] == PRIVATE_TEXT
+        assert destination.stat().st_mode & 0o777 == 0o600
+        with sqlite3.connect(destination) as backup:
+            assert backup.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
+            assert backup.execute("SELECT COUNT(*) FROM consultations").fetchone()[0] == 1
+            assert backup.execute("SELECT clinical_text FROM consultations").fetchone()[0] == PRIVATE_TEXT
+    finally:
+        connection.close()
+
+
+def test_existing_destination_is_never_overwritten(tmp_path):
+    source, destination = tmp_path / "source.sqlite", tmp_path / "backup.sqlite"
+    seed(source).close()
+    assert run_backup(source, destination).returncode == 0
+    original = destination.read_bytes()
+    second = run_backup(source, destination)
+    assert second.returncode != 0
+    assert second.stderr == "Backup failed; no verified backup was produced.\n"
+    assert '"verified": true' not in second.stdout.lower()
+    assert destination.read_bytes() == original
+
+
+@pytest.mark.parametrize("source_kind", ["missing", "corrupt"])
+def test_failed_backup_has_no_verified_result_or_new_source(tmp_path, source_kind):
+    source, destination = tmp_path / "source.sqlite", tmp_path / "backup.sqlite"
+    if source_kind == "corrupt":
+        source.write_text(PRIVATE_TEXT)
+    result = run_backup(source, destination)
+    assert result.returncode != 0
+    assert result.stdout == ""
+    assert result.stderr == "Backup failed; no verified backup was produced.\n"
+    assert PRIVATE_TEXT not in result.stderr
+    assert not destination.exists()
+    assert source.exists() == (source_kind == "corrupt")
+
+
+def test_same_source_or_symlink_destination_is_rejected(tmp_path):
+    source = tmp_path / "source.sqlite"
+    seed(source).close()
+    original = source.read_bytes()
+    same = run_backup(source, source)
+    assert same.returncode != 0
+    assert same.stderr == "Backup failed; no verified backup was produced.\n"
+    link = tmp_path / "link.sqlite"
+    link.symlink_to(source)
+    assert run_backup(source, link).returncode != 0
+    assert link.is_symlink()
+    assert source.read_bytes() == original
+
+
+def load_module():
+    spec = importlib.util.spec_from_file_location("backup_database", SCRIPT)
+    assert spec is not None and spec.loader is not None
+    module = importlib.util.module_from_spec(spec)
+    spec.loader.exec_module(module)
+    return module
+
+
+def test_verification_failure_removes_partial_backup(tmp_path, monkeypatch, capsys):
+    # Fault only the integrity verifier, after the real SQLite backup has completed.
+    module = load_module()
+    source, destination = tmp_path / "source.sqlite", tmp_path / "backup.sqlite"
+    seed(source).close()
+    def reject(_connection):
+        raise ValueError(PRIVATE_TEXT)
+    monkeypatch.setattr(module, "verify_integrity", reject)
+    assert module.main(["--source", str(source), "--destination", str(destination)]) == 1
+    output = capsys.readouterr()
+    assert output.out == ""
+    assert PRIVATE_TEXT not in output.err
+    assert not destination.exists()
+
+
+def test_concurrent_commit_does_not_change_the_verified_snapshot(tmp_path, monkeypatch):
+    module = load_module()
+    source, destination = tmp_path / "source.sqlite", tmp_path / "backup.sqlite"
+    writer = seed(source)
+    original_counts = module.table_counts
+    calls = 0
+    def counts_then_write(connection):
+        nonlocal calls
+        counts = original_counts(connection)
+        calls += 1
+        if calls == 1:
+            writer.execute("INSERT INTO consultations(clinical_text) VALUES (?)", ("NEW-SYNTHETIC-ROW",))
+            writer.commit()
+        return counts
+    monkeypatch.setattr(module, "table_counts", counts_then_write)
+    try:
+        result = module.backup_database(source, destination)
+        assert result["table_counts"]["consultations"] == 1
+        assert writer.execute("SELECT COUNT(*) FROM consultations").fetchone()[0] == 2
+        with sqlite3.connect(destination) as backup:
+            assert backup.execute("SELECT COUNT(*) FROM consultations").fetchone()[0] == 1
+    finally:
+        writer.close()
+
+
+def test_count_mismatch_is_not_reported_as_verified(tmp_path, monkeypatch, capsys):
+    module = load_module()
+    source, destination = tmp_path / "source.sqlite", tmp_path / "backup.sqlite"
+    seed(source).close()
+    original_counts = module.table_counts
+    calls = 0
+    def mismatched_counts(connection):
+        nonlocal calls
+        counts = original_counts(connection)
+        calls += 1
+        if calls == 2:
+            counts["consultations"] += 1
+        return counts
+    monkeypatch.setattr(module, "table_counts", mismatched_counts)
+    assert module.main(["--source", str(source), "--destination", str(destination)]) == 1
+    assert capsys.readouterr().out == ""
+    assert not destination.exists()

```

