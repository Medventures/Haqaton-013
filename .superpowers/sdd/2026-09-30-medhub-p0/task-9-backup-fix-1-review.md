# Backup fix round1 isolated review

Original findings: task-9-backup-review-verdict.md. Report: task-9-backup-report.md. Focused11 passed; full run pending. Review ONLY fixes and direct affected boundaries; original backup reviewer p0_preview. No live data.

## Script diff
```diff
--- /tmp/medhub-backup-before-fix.iqBJeV/backup_database.py	2026-09-30 14:36:27.770443010 +0500
+++ scripts/backup_database.py	2026-09-30 14:37:03.747903966 +0500
@@ -6,75 +6,75 @@
 errors deliberately omit database contents, SQL and exception details.
 """
 from __future__ import annotations
 
 import argparse
 from contextlib import closing
 import json
 import os
 from pathlib import Path
 import sqlite3
+import stat
 import sys
+import tempfile
 
 
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
-    created_stat = None
-    verified = False
-    try:
+    # Never open or unlink the public destination. Only publish a completed
+    # private staging inode using an atomic, no-overwrite hard link.
+    with tempfile.TemporaryDirectory(prefix=".medhub-backup-", dir=destination.parent) as temporary:
+        staged = Path(temporary) / "verified.sqlite"
         # mode=ro preserves a missing source and reads committed WAL normally.
         with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as original:
             # Pin the same read snapshot for both the backup API and row counts.
             original.execute("BEGIN")
             counts = table_counts(original)
-            descriptor = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
+            descriptor = os.open(staged, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
             try:
-                created_stat = os.fstat(descriptor)
                 os.fchmod(descriptor, 0o600)
+                staged_identity = os.fstat(descriptor)
             finally:
                 os.close(descriptor)
-            with closing(sqlite3.connect(destination)) as backup:
+            with closing(sqlite3.connect(staged)) as backup:
                 original.backup(backup)
                 # Produce one independently readable file, not a WAL-dependent set.
                 backup.execute("PRAGMA journal_mode=DELETE")
                 verify_integrity(backup)
                 if table_counts(backup) != counts:
                     raise ValueError("Backup table counts do not match")
             original.rollback()
-        verified = True
-        return {"verified": True, "integrity_check": "ok", "table_counts": counts}
-    finally:
-        if not verified and created_stat is not None:
-            # Remove only the incomplete file created by this invocation. Never
-            # unlink an existing destination or a path someone has replaced.
-            try:
-                current = destination.lstat()
-                if (current.st_dev, current.st_ino) == (created_stat.st_dev, created_stat.st_ino):
-                    destination.unlink()
-            except FileNotFoundError:
-                pass
+        current = staged.lstat()
+        if (current.st_dev, current.st_ino) != (staged_identity.st_dev, staged_identity.st_ino):
+            raise ValueError("Staging identity changed")
+        os.link(staged, destination, follow_symlinks=False)
+    published = destination.lstat()
+    if ((published.st_dev, published.st_ino) != (staged_identity.st_dev, staged_identity.st_ino)
+            or not stat.S_ISREG(published.st_mode) or stat.S_IMODE(published.st_mode) != 0o600):
+        raise ValueError("Published backup identity or permissions changed")
+    return {"verified": True, "integrity_check": "ok", "table_counts": counts}
 
 
 def main(argv: list[str] | None = None) -> int:
     parser = argparse.ArgumentParser(description=__doc__)
     parser.add_argument("--source", type=Path, required=True)
     parser.add_argument("--destination", type=Path, required=True)
     args = parser.parse_args(argv)
     try:
         result = backup_database(args.source, args.destination)
     except Exception:

```

## Tests diff
```diff
--- /tmp/medhub-backup-before-fix.iqBJeV/test_backup_database.py	2026-09-30 14:36:27.770553889 +0500
+++ backend/tests/test_backup_database.py	2026-09-30 14:36:54.077779946 +0500
@@ -149,10 +149,71 @@
         nonlocal calls
         counts = original_counts(connection)
         calls += 1
         if calls == 2:
             counts["consultations"] += 1
         return counts
     monkeypatch.setattr(module, "table_counts", mismatched_counts)
     assert module.main(["--source", str(source), "--destination", str(destination)]) == 1
     assert capsys.readouterr().out == ""
     assert not destination.exists()
+
+
+def test_destination_substitution_never_opens_or_overwrites_target(tmp_path, monkeypatch):
+    module = load_module()
+    source, destination, target = tmp_path / "source.sqlite", tmp_path / "backup.sqlite", tmp_path / "target.sqlite"
+    seed(source).close()
+    with sqlite3.connect(target) as connection:
+        connection.execute("CREATE TABLE target_marker (value TEXT)")
+        connection.execute("INSERT INTO target_marker VALUES ('must survive')")
+    original_target = target.read_bytes()
+    original_close = module.os.close
+    def swap_after_close(descriptor):
+        original_close(descriptor)
+        if destination.exists() and not destination.is_symlink():
+            destination.unlink()
+            destination.symlink_to(target)
+    monkeypatch.setattr(module.os, "close", swap_after_close)
+    try:
+        result = module.backup_database(source, destination)
+    except (OSError, ValueError):
+        result = None
+    assert target.read_bytes() == original_target
+    if result is not None:
+        assert result["verified"] and not destination.is_symlink()
+        assert destination.stat().st_mode & 0o777 == 0o600
+
+
+def test_destination_created_during_verification_is_preserved(tmp_path, monkeypatch):
+    module = load_module()
+    source, destination, target = tmp_path / "source.sqlite", tmp_path / "backup.sqlite", tmp_path / "target.sqlite"
+    seed(source).close()
+    target.write_text("unrelated destination")
+    original_verify = module.verify_integrity
+    def replace_destination(connection):
+        if destination.exists():
+            destination.unlink()
+        destination.symlink_to(target)
+        original_verify(connection)
+    monkeypatch.setattr(module, "verify_integrity", replace_destination)
+    with pytest.raises((OSError, ValueError)):
+        module.backup_database(source, destination)
+    assert destination.is_symlink()
+    assert target.read_text() == "unrelated destination"
+
+
+def test_replacement_after_publication_fails_without_deleting_replacement(tmp_path, monkeypatch):
+    module = load_module()
+    source, destination, target = tmp_path / "source.sqlite", tmp_path / "backup.sqlite", tmp_path / "target.sqlite"
+    seed(source).close()
+    target.write_text("must survive publication race")
+    original_link = module.os.link
+    def replace_after_link(*args, **kwargs):
+        original_link(*args, **kwargs)
+        destination.unlink()
+        destination.symlink_to(target)
+    monkeypatch.setattr(module.os, "link", replace_after_link)
+    with pytest.raises(ValueError, match="identity or permissions"):
+        module.backup_database(source, destination)
+    assert destination.is_symlink()
+    assert target.read_text() == "must survive publication race"
+    assert not list(tmp_path.glob(".medhub-backup-*"))

```

