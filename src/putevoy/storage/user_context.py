"""Контекст текущего пользователя — для per-user изоляции данных.

ContextVar устанавливается в auth_middleware на каждый HTTP-запрос
и автоматически прокидывается во все вызовы repo-функций внутри запроса.

Так все queries фильтруются по текущему user_id без необходимости
передавать его явным аргументом через десятки функций.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator, Optional


_current_user_id: ContextVar[Optional[int]] = ContextVar(
    "putevoy_current_user_id", default=None,
)


def get_current_user_id() -> Optional[int]:
    """Вернуть id залогиненного пользователя, или None вне auth-контекста."""
    return _current_user_id.get()


def set_current_user_id(user_id: Optional[int]) -> object:
    """Установить current_user_id; вернуть token для сброса в finally."""
    return _current_user_id.set(user_id)


def reset_current_user_id(token: object) -> None:
    _current_user_id.reset(token)  # type: ignore[arg-type]


@contextmanager
def user_context(user_id: Optional[int]) -> Iterator[None]:
    """Контекст-менеджер для тестов и CLI — упрощает временную установку user_id."""
    token = _current_user_id.set(user_id)
    try:
        yield
    finally:
        _current_user_id.reset(token)
