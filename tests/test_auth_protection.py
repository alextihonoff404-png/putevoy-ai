"""Проверка, что middleware блокирует все защищённые роуты для незалогиненных.

Регресс-кейс: до middleware любой мог зайти на /dashboard / /setup / /api/*
без авторизации.
"""
from __future__ import annotations

from fastapi.testclient import TestClient


# --- Публичные пути: всегда доступны ---------------------------------------


def test_login_page_is_public(anon_client: TestClient):
    r = anon_client.get("/login")
    assert r.status_code == 200
    assert "ход" in r.text.lower() or "войти" in r.text.lower()


def test_register_page_is_public(anon_client: TestClient):
    r = anon_client.get("/register")
    assert r.status_code == 200


# --- Защищённые HTML-страницы: редирект на /login --------------------------


PROTECTED_HTML_PATHS = [
    "/",
    "/setup",
    "/dashboard",
    "/routes",
    "/vehicles",
    "/generate",
    "/history",
    "/download/waybill/2026/4",
    "/download/fuel-month/2026/4",
    "/download/fuel-full",
    "/preview/waybill/2026/4",
]


def test_protected_html_paths_redirect_to_login(anon_client: TestClient):
    for path in PROTECTED_HTML_PATHS:
        r = anon_client.get(path, follow_redirects=False)
        assert r.status_code == 302, f"{path} должен был отдать 302, отдал {r.status_code}"
        assert r.headers["location"] == "/login", (
            f"{path} должен редиректить на /login, а редиректит на {r.headers.get('location')}"
        )


# --- Защищённые API endpoints: 401 JSON ------------------------------------


def test_api_endpoints_return_401_for_anon(anon_client: TestClient):
    # GET варианта нет — это POST endpoints, но middleware должен заблокировать
    # любой метод. Проверим POST.
    r = anon_client.post("/api/calc-distance", data={"address": "СПб, Невский 1"})
    assert r.status_code == 401
    body = r.json()
    assert body["ok"] is False
    assert "авториз" in body["error"].lower()


def test_api_preview_generate_blocked_for_anon(anon_client: TestClient):
    r = anon_client.post("/api/preview-generate", data={"year": "2026", "month": "4"})
    assert r.status_code == 401


# --- POST на защищённые формы: тоже редирект -------------------------------


def test_post_setup_blocked_for_anon(anon_client: TestClient):
    r = anon_client.post("/setup", data={"organization_name": "test"}, follow_redirects=False)
    # Не должно сохраниться. Middleware вернёт 302 на /login.
    assert r.status_code == 302
    assert r.headers["location"] == "/login"


# --- Логаут чистит сессию --------------------------------------------------


def test_logout_blocks_further_access(authed_client: TestClient):
    # Залогинен — /dashboard доступен (редиректит на /setup если нет профиля)
    r = authed_client.get("/dashboard", follow_redirects=False)
    assert r.status_code in (200, 302)
    # location либо рендер либо /setup — главное не /login
    if r.status_code == 302:
        assert r.headers["location"] != "/login"

    # Делаем logout
    r = authed_client.post("/logout", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/login"

    # После logout те же запросы должны блокироваться
    r = authed_client.get("/dashboard", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "/login"


# --- Доступ после регистрации/логина ---------------------------------------


def test_after_login_dashboard_accessible(anon_client: TestClient):
    # Регистрация
    r = anon_client.post("/register", data={
        "email": "newuser@example.com",
        "password": "supersecret",
        "password_confirm": "supersecret",
    }, follow_redirects=False)
    assert r.status_code == 303
    # После регистрации /dashboard уже доступен (но редиректит на /setup, т.к. профиля нет)
    r = anon_client.get("/setup", follow_redirects=False)
    assert r.status_code == 200
