"""Репозиторий для модели User: регистрация, логин, поиск.

Использует bcrypt напрямую — стандарт для хеширования паролей.
bcrypt принимает максимум 72 байта (см. ограничение алгоритма), поэтому
длинные пароли усекаются. Для практических целей этого хватает.
"""
from __future__ import annotations

from typing import Optional

import bcrypt
from sqlalchemy import select

from . import db as _db
from .models import Driver, Profile, User, Vehicle


def _to_bytes(s: str) -> bytes:
    """Подготовить пароль для bcrypt: utf-8 + усечение до 72 байт."""
    return s.encode("utf-8")[:72]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_to_bytes(password), bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_to_bytes(password), hashed.encode("ascii"))
    except Exception:
        return False


def create_user(email: str, password: str) -> Optional[User]:
    """Создать пользователя. Вернёт None, если email уже занят.

    Если этот user — первый в БД и в системе есть «осиротевшие» данные
    (Profile/Driver/Vehicle с user_id IS NULL — legacy до миграции),
    они автоматически привязываются к нему. Так первый, кто зарегистрируется
    на сервере с уже существующими данными, получает их.
    """
    email = email.strip().lower()
    with _db.SessionLocal() as s:
        existing = s.execute(select(User).where(User.email == email)).scalar_one_or_none()
        if existing:
            return None

        # Проверяем, не первый ли это user — ДО создания нового
        is_first_user = s.execute(select(User)).scalars().first() is None

        u = User(email=email, password_hash=hash_password(password))
        s.add(u)
        s.flush()  # чтобы u.id заполнился до миграции

        if is_first_user:
            # Привязываем все orphan-данные к этому пользователю
            _migrate_orphans_to_user(s, u.id)

        s.commit()
        s.refresh(u)
        return u


def _migrate_orphans_to_user(session, user_id: int) -> None:
    """Все записи с user_id IS NULL → текущему user.

    Вызывается ровно один раз — при регистрации первого пользователя в БД.
    """
    for orphan in session.execute(select(Profile).where(Profile.user_id.is_(None))).scalars():
        orphan.user_id = user_id
    for orphan in session.execute(select(Driver).where(Driver.user_id.is_(None))).scalars():
        orphan.user_id = user_id
    for orphan in session.execute(select(Vehicle).where(Vehicle.user_id.is_(None))).scalars():
        orphan.user_id = user_id


def get_user_by_email(email: str) -> Optional[User]:
    email = email.strip().lower()
    with _db.SessionLocal() as s:
        return s.execute(select(User).where(User.email == email)).scalar_one_or_none()


def get_user_by_id(user_id: int) -> Optional[User]:
    with _db.SessionLocal() as s:
        return s.get(User, user_id)


def authenticate(email: str, password: str) -> Optional[User]:
    """Проверить email+пароль. Вернёт User при успехе или None."""
    user = get_user_by_email(email)
    if not user:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


def users_count() -> int:
    """Сколько пользователей зарегистрировано (для миграции)."""
    with _db.SessionLocal() as s:
        return len(list(s.execute(select(User)).scalars()))
