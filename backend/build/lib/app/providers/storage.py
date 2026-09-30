"""Path-safe local audio storage."""

import os
import re
import uuid
from pathlib import Path


_SAFE_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,254}\Z")


class LocalStorage:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()

    def _path(self, key: str) -> Path:
        if not isinstance(key, str) or not _SAFE_KEY.fullmatch(key) or key in {".", ".."}:
            raise ValueError("Invalid storage key")
        path = self.root / key
        if path.is_symlink():
            raise ValueError("Invalid storage key")
        return path

    def save(self, key: str, data: bytes) -> str:
        target = self._path(key)
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = self.root / f".{uuid.uuid4().hex}.tmp"
        try:
            with temporary.open("xb") as file:
                file.write(data)
                file.flush()
                os.fsync(file.fileno())
            if target.is_symlink():
                raise ValueError("Invalid storage key")
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
        return key

    def get(self, key: str) -> Path:
        path = self._path(key)
        if not path.is_file():
            raise FileNotFoundError("Stored audio not found")
        return path

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)
