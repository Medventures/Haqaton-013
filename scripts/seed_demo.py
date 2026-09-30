"""Create an isolated, synthetic SQLite database for a local MedHub demo."""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import sys

from alembic import command
from alembic.config import Config
from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.auth import password_hash  # noqa: E402
from app.config import Settings  # noqa: E402
from app.db import make_engine, make_session_factory  # noqa: E402
from app.models import Consultation, User, now_utc  # noqa: E402


DATABASE = ROOT / "storage" / "medhub-demo.db"
SEED_DATA = json.loads((ROOT / "seed" / "demo.json").read_text(encoding="utf-8"))
DOCTOR = SEED_DATA["doctor"]
DEMO_CONSULTATION = SEED_DATA["consultations"][0]
PATIENT_ID = DEMO_CONSULTATION["external_patient_id"]


def existing_seed_state() -> bool:
    if DATABASE.is_symlink():
        raise RuntimeError("Refusing a symlink at the demo database path")
    if not DATABASE.exists():
        return False
    connection = sqlite3.connect(DATABASE.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_schema WHERE type='table'")}
        if not {"users", "consultations"}.issubset(tables):
            raise RuntimeError("The demo database file already exists and is not a completed seed")
        users = connection.execute(
            "SELECT id FROM users WHERE username=? AND role=?", (DOCTOR["username"], "doctor")
        ).fetchall()
        consultations = connection.execute(
            "SELECT status, created_by FROM consultations WHERE external_patient_id=?", (PATIENT_ID,)
        ).fetchall()
        if len(users) == 1 and consultations == [(DEMO_CONSULTATION["status"], users[0][0])]:
            return True
        raise RuntimeError("Refusing to seed into an existing or partially populated database")
    finally:
        connection.close()


def seed() -> dict[str, object]:
    if existing_seed_state():
        return {"seeded": False, "already_seeded": True, "database": str(DATABASE.relative_to(ROOT))}

    DATABASE.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    settings = Settings(
        app_mode="demo",
        database_url=f"sqlite:///{DATABASE}",
        doctor_username=DOCTOR["username"],
        llm_provider="demo",
    )
    migration_config = Config(str(BACKEND / "alembic.ini"))
    migration_config.set_main_option("script_location", str(BACKEND / "alembic"))
    migration_config.attributes["database_url"] = settings.database_url
    command.upgrade(migration_config, "head")

    engine = make_engine(settings.database_url)
    session_factory = make_session_factory(engine)
    try:
        with session_factory() as session:
            doctor = User(
                username=DOCTOR["username"],
                password_hash=password_hash.hash(DOCTOR["password"]),
                role="doctor",
                display_name=DOCTOR["display_name"],
            )
            session.add(doctor)
            session.flush()
            session.add(Consultation(
                external_patient_id=DEMO_CONSULTATION["external_patient_id"],
                template_id=DEMO_CONSULTATION["template_id"],
                status=DEMO_CONSULTATION["status"],
                created_by=doctor.id,
                created_at=now_utc(),
                updated_at=now_utc(),
            ))
            session.commit()
    finally:
        engine.dispose()

    return {
        "seeded": True,
        "database": str(DATABASE.relative_to(ROOT)),
        "consultation": PATIENT_ID,
        "status": DEMO_CONSULTATION["status"],
        "login": DOCTOR["username"],
        "password": DOCTOR["password"],
        "provider": "demo; no external AI request",
    }


def main() -> int:
    try:
        result = seed()
    except Exception as error:
        print(json.dumps({"seeded": False, "error": str(error)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
