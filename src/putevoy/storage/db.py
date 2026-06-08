"""Подключение к БД и сессии."""
from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

DATA_DIR = Path(os.environ.get("PUTEVOY_DATA_DIR", Path.cwd() / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "putevoy.db"

engine = create_engine(f"sqlite:///{DB_PATH}", echo=False, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def reset_db_for_tests(test_db_path: Path) -> None:
    """Перенастроить engine на отдельный test DB. Используется в pytest fixtures."""
    global engine, SessionLocal
    engine = create_engine(f"sqlite:///{test_db_path}", echo=False, future=True)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
