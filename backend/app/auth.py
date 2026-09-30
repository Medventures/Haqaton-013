from __future__ import annotations

from datetime import datetime, timedelta, timezone
import secrets

import jwt
from fastapi import HTTPException, status
from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import User


password_hash = PasswordHash.recommended()


def create_initial_doctor(session: Session, settings) -> None:
    if settings.app_mode == "live":
        try:
            configured_demo_password = password_hash.verify("demo-doctor", settings.doctor_password_hash)
        except Exception:
            raise ValueError("DOCTOR_PASSWORD_HASH is invalid") from None
        if configured_demo_password:
            raise ValueError("Live mode cannot use the demo password")
        for stored_user in session.scalars(select(User)):
            try:
                is_demo_password = password_hash.verify("demo-doctor", stored_user.password_hash)
            except Exception:
                is_demo_password = False
            if is_demo_password:
                stored_user.password_hash = password_hash.hash(secrets.token_urlsafe(48))
        session.commit()
    hashed = settings.doctor_password_hash
    if settings.app_mode == "demo":
        hashed = password_hash.hash("demo-doctor")
    existing = session.scalar(select(User).where(User.username == settings.doctor_username))
    if existing is not None:
        # The starter demo credential is only for the first boot of a database.
        # Keep intentional local seed/password changes across later restarts.
        if settings.app_mode == "live" and existing.password_hash != hashed:
            existing.password_hash = hashed
            session.commit()
        return
    user = User(
        username=settings.doctor_username,
        password_hash=hashed,
        role="doctor",
        display_name="Демо врач" if settings.app_mode == "demo" else settings.doctor_username,
    )
    session.add(user)
    session.commit()


def authenticate(session: Session, username: str, password: str) -> User:
    user = session.scalar(select(User).where(User.username == username))
    if user is None or not password_hash.verify(password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Неверные учётные данные")
    return user


def make_token(user: User, secret: str) -> str:
    return jwt.encode(
        {"sub": user.id, "exp": datetime.now(timezone.utc) + timedelta(hours=8)},
        secret,
        algorithm="HS256",
    )


def decode_token(token: str, secret: str) -> str:
    try:
        payload = jwt.decode(token, secret, algorithms=["HS256"])
        subject = payload["sub"]
        if not isinstance(subject, str):
            raise ValueError("invalid subject")
        return subject
    except (jwt.PyJWTError, KeyError, ValueError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Требуется вход") from None
