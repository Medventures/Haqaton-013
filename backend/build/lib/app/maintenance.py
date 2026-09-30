"""Explicit maintenance command for audio retention."""

import argparse

from .config import Settings
from .db import make_engine, make_session_factory
from .providers.storage import LocalStorage
from .service import cleanup_expired_audio


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["cleanup-audio"])
    args = parser.parse_args()
    settings = Settings.from_env()
    settings.validate()
    engine = make_engine(settings.database_url)
    try:
        with make_session_factory(engine)() as session:
            removed = cleanup_expired_audio(session, LocalStorage(settings.audio_storage_dir), settings.audio_retention_days)
        print(f"Removed {removed} expired audio record(s)")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
