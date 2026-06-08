"""Общие фикстуры для тестов веб-приложения.

Чтобы тесты не делили production-БД, переключаем PUTEVOY_DATA_DIR на tmp
ДО первого импорта web/app.py.
"""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture()
def fresh_db(tmp_path: Path, monkeypatch):
    """Пере-инициализировать SQLite на временной директории.

    Меняет env-переменную и патчит db.engine + db.SessionLocal.
    """
    test_dir = tmp_path / "data"
    test_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("PUTEVOY_DATA_DIR", str(test_dir))

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from putevoy.storage import db as db_mod
    from putevoy.storage.models import Base

    new_engine = create_engine(f"sqlite:///{test_dir / 'putevoy.db'}", future=True)
    new_session = sessionmaker(bind=new_engine, autoflush=False, autocommit=False, future=True)

    monkeypatch.setattr(db_mod, "engine", new_engine)
    monkeypatch.setattr(db_mod, "SessionLocal", new_session)
    Base.metadata.create_all(new_engine)

    yield new_session


@pytest.fixture()
def authed_client(fresh_db):
    """TestClient с уже залогиненным тестовым пользователем.

    Регистрирует пользователя, логинит — и устанавливает user_context на всё
    время теста, чтобы прямые вызовы repo-функций из теста (не через HTTP)
    работали с тем же user'ом.
    """
    from fastapi.testclient import TestClient
    from putevoy.web.app import app
    from putevoy.storage.auth_repo import create_user
    from putevoy.storage.user_context import set_current_user_id, reset_current_user_id

    user = create_user("test@example.com", "testpass123")
    token = set_current_user_id(user.id)
    try:
        c = TestClient(app)
        c.post("/login", data={"email": "test@example.com", "password": "testpass123"})
        yield c
    finally:
        reset_current_user_id(token)


@pytest.fixture()
def anon_client(fresh_db):
    """TestClient без логина — для проверки, что защищённые роуты блокируют доступ."""
    from fastapi.testclient import TestClient
    from putevoy.web.app import app

    return TestClient(app)
