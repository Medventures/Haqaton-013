import importlib.util
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "backup_database.py"
PRIVATE_TEXT = "SYNTHETIC-PRIVATE-CONSULTATION-DO-NOT-PRINT"


def run_backup(source, destination):
    return subprocess.run([sys.executable, str(SCRIPT), "--source", str(source), "--destination", str(destination)],
                          capture_output=True, text=True, timeout=20)


def seed(path):
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("CREATE TABLE consultations (id INTEGER PRIMARY KEY, clinical_text TEXT)")
    connection.execute('CREATE TABLE "odd table""name" (value TEXT)')
    connection.execute("INSERT INTO consultations(clinical_text) VALUES (?)", (PRIVATE_TEXT,))
    connection.execute('INSERT INTO "odd table""name" VALUES (?)', (PRIVATE_TEXT,))
    connection.commit()
    return connection


def test_backup_preserves_wal_data_source_and_restricts_permissions(tmp_path):
    source = tmp_path / "source.sqlite"
    destination = tmp_path / "backup.sqlite"
    connection = seed(source)
    try:
        assert Path(str(source) + "-wal").is_file()
        original_bytes = source.read_bytes()
        result = run_backup(source, destination)
        assert result.returncode == 0, result.stderr
        summary = json.loads(result.stdout)
        assert summary == {"verified": True, "integrity_check": "ok", "table_counts": {"consultations": 1, 'odd table"name': 1}}
        assert PRIVATE_TEXT not in result.stdout + result.stderr
        assert source.read_bytes() == original_bytes
        assert connection.execute("SELECT clinical_text FROM consultations").fetchone()[0] == PRIVATE_TEXT
        assert destination.stat().st_mode & 0o777 == 0o600
        with sqlite3.connect(destination) as backup:
            assert backup.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert backup.execute("SELECT COUNT(*) FROM consultations").fetchone()[0] == 1
            assert backup.execute("SELECT clinical_text FROM consultations").fetchone()[0] == PRIVATE_TEXT
    finally:
        connection.close()


def test_existing_destination_is_never_overwritten(tmp_path):
    source, destination = tmp_path / "source.sqlite", tmp_path / "backup.sqlite"
    seed(source).close()
    assert run_backup(source, destination).returncode == 0
    original = destination.read_bytes()
    second = run_backup(source, destination)
    assert second.returncode != 0
    assert second.stderr == "Backup failed; no verified backup was produced.\n"
    assert '"verified": true' not in second.stdout.lower()
    assert destination.read_bytes() == original


@pytest.mark.parametrize("source_kind", ["missing", "corrupt"])
def test_failed_backup_has_no_verified_result_or_new_source(tmp_path, source_kind):
    source, destination = tmp_path / "source.sqlite", tmp_path / "backup.sqlite"
    if source_kind == "corrupt":
        source.write_text(PRIVATE_TEXT)
    result = run_backup(source, destination)
    assert result.returncode != 0
    assert result.stdout == ""
    assert result.stderr == "Backup failed; no verified backup was produced.\n"
    assert PRIVATE_TEXT not in result.stderr
    assert not destination.exists()
    assert source.exists() == (source_kind == "corrupt")


def test_same_source_or_symlink_destination_is_rejected(tmp_path):
    source = tmp_path / "source.sqlite"
    seed(source).close()
    original = source.read_bytes()
    same = run_backup(source, source)
    assert same.returncode != 0
    assert same.stderr == "Backup failed; no verified backup was produced.\n"
    link = tmp_path / "link.sqlite"
    link.symlink_to(source)
    assert run_backup(source, link).returncode != 0
    assert link.is_symlink()
    assert source.read_bytes() == original


def load_module():
    spec = importlib.util.spec_from_file_location("backup_database", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_verification_failure_removes_partial_backup(tmp_path, monkeypatch, capsys):
    # Fault only the integrity verifier, after the real SQLite backup has completed.
    module = load_module()
    source, destination = tmp_path / "source.sqlite", tmp_path / "backup.sqlite"
    seed(source).close()
    def reject(_connection):
        raise ValueError(PRIVATE_TEXT)
    monkeypatch.setattr(module, "verify_integrity", reject)
    assert module.main(["--source", str(source), "--destination", str(destination)]) == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert PRIVATE_TEXT not in output.err
    assert not destination.exists()


def test_concurrent_commit_does_not_change_the_verified_snapshot(tmp_path, monkeypatch):
    module = load_module()
    source, destination = tmp_path / "source.sqlite", tmp_path / "backup.sqlite"
    writer = seed(source)
    original_counts = module.table_counts
    calls = 0
    def counts_then_write(connection):
        nonlocal calls
        counts = original_counts(connection)
        calls += 1
        if calls == 1:
            writer.execute("INSERT INTO consultations(clinical_text) VALUES (?)", ("NEW-SYNTHETIC-ROW",))
            writer.commit()
        return counts
    monkeypatch.setattr(module, "table_counts", counts_then_write)
    try:
        result = module.backup_database(source, destination)
        assert result["table_counts"]["consultations"] == 1
        assert writer.execute("SELECT COUNT(*) FROM consultations").fetchone()[0] == 2
        with sqlite3.connect(destination) as backup:
            assert backup.execute("SELECT COUNT(*) FROM consultations").fetchone()[0] == 1
    finally:
        writer.close()


def test_count_mismatch_is_not_reported_as_verified(tmp_path, monkeypatch, capsys):
    module = load_module()
    source, destination = tmp_path / "source.sqlite", tmp_path / "backup.sqlite"
    seed(source).close()
    original_counts = module.table_counts
    calls = 0
    def mismatched_counts(connection):
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


def test_destination_substitution_never_opens_or_overwrites_target(tmp_path, monkeypatch):
    module = load_module()
    source, destination, target = tmp_path / "source.sqlite", tmp_path / "backup.sqlite", tmp_path / "target.sqlite"
    seed(source).close()
    with sqlite3.connect(target) as connection:
        connection.execute("CREATE TABLE target_marker (value TEXT)")
        connection.execute("INSERT INTO target_marker VALUES ('must survive')")
    original_target = target.read_bytes()
    original_close = module.os.close
    def swap_after_close(descriptor):
        original_close(descriptor)
        if destination.exists() and not destination.is_symlink():
            destination.unlink()
            destination.symlink_to(target)
    monkeypatch.setattr(module.os, "close", swap_after_close)
    try:
        result = module.backup_database(source, destination)
    except (OSError, ValueError):
        result = None
    assert target.read_bytes() == original_target
    if result is not None:
        assert result["verified"] and not destination.is_symlink()
        assert destination.stat().st_mode & 0o777 == 0o600


def test_destination_created_during_verification_is_preserved(tmp_path, monkeypatch):
    module = load_module()
    source, destination, target = tmp_path / "source.sqlite", tmp_path / "backup.sqlite", tmp_path / "target.sqlite"
    seed(source).close()
    target.write_text("unrelated destination")
    original_verify = module.verify_integrity
    def replace_destination(connection):
        if destination.exists():
            destination.unlink()
        destination.symlink_to(target)
        original_verify(connection)
    monkeypatch.setattr(module, "verify_integrity", replace_destination)
    with pytest.raises((OSError, ValueError)):
        module.backup_database(source, destination)
    assert destination.is_symlink()
    assert target.read_text() == "unrelated destination"


def test_replacement_after_publication_fails_without_deleting_replacement(tmp_path, monkeypatch):
    module = load_module()
    source, destination, target = tmp_path / "source.sqlite", tmp_path / "backup.sqlite", tmp_path / "target.sqlite"
    seed(source).close()
    target.write_text("must survive publication race")
    original_link = module.os.link
    def replace_after_link(*args, **kwargs):
        original_link(*args, **kwargs)
        destination.unlink()
        destination.symlink_to(target)
    monkeypatch.setattr(module.os, "link", replace_after_link)
    with pytest.raises(ValueError, match="identity or permissions"):
        module.backup_database(source, destination)
    assert destination.is_symlink()
    assert target.read_text() == "must survive publication race"
    assert not list(tmp_path.glob(".medhub-backup-*"))
