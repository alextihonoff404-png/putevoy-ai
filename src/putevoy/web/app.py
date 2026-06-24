"""FastAPI веб-приложение — многостраничный UI.

Маршруты:
    /              → редирект на /setup или /dashboard
    /setup         → мастер первичной настройки
    /routes        → каталог адресов (CRUD)
    /dashboard     → список месяцев + переход к генерации
    /generate      → форма генерации нового месяца
    /history       → история прогонов + ссылки на скачивание

Запуск:
    uvicorn putevoy.web.app:app --reload
"""
from __future__ import annotations

import os
import re
import tempfile
from datetime import date
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from ..generator.calendar import MONTH_NOMINATIVE_RU, working_days
from ..generator.models import Fueling
from ..geocoding.address_parser import compose_address, parse_address
from ..geocoding.service import DistanceError, DistanceResult, calc_distance
from ..parsing.fuel_log_importer import import_state_from_xlsx
from ..parsing.fueling_parser import parse_fuelings
from ..storage.repo import (
    add_route, add_vehicle, current_vehicle_id, delete_route, delete_run,
    delete_vehicle, get_profile, get_vehicle, get_vehicle_state, has_profile,
    init_db, list_routes, list_runs, list_vehicles, save_setup,
    set_active_vehicle, update_route, update_vehicle, update_vehicle_state,
)
from ..storage.auth_repo import (
    authenticate, create_user, get_user_by_id, users_count,
)
from ..storage.user_context import set_current_user_id, reset_current_user_id
from .service import (
    get_existing_fuelings, get_existing_skip_dates, preview_run, run_and_persist,
    write_fuel_log_for_month, write_full_fuel_log, write_waybill_for_run,
)

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR.mkdir(exist_ok=True)
STATIC_DIR.mkdir(exist_ok=True)
DOWNLOADS_DIR = Path(tempfile.gettempdir()) / "putevoy_downloads"
DOWNLOADS_DIR.mkdir(exist_ok=True)

# Инициализируем БД при импорте модуля — идемпотентно.
init_db()

app = FastAPI(title="Путевой.AI")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


def _to_float(s: str) -> float:
    """Принять число с запятой или точкой как десятичным разделителем."""
    return float(str(s).replace(",", ".").strip())


# --- Auth: helpers ---------------------------------------------------------

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _current_user(request: Request):
    """Вернуть User по сессии или None."""
    uid = request.session.get("user_id")
    if not uid:
        return None
    return get_user_by_id(uid)


# Пути, доступные без авторизации. Точные совпадения и префиксы.
_PUBLIC_PATHS = {"/", "/login", "/register"}
_PUBLIC_PREFIXES = ("/static/",)


def _is_public(path: str) -> bool:
    if path in _PUBLIC_PATHS:
        return True
    for prefix in _PUBLIC_PREFIXES:
        if path.startswith(prefix):
            return True
    return False


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """Гейт авторизации + установка ContextVar текущего пользователя.

    Для HTML-страниц без auth — редирект на /login.
    Для /api/* — 401 JSON (фронтенд может корректно отреагировать).
    Для /download/* и /preview/* — тоже редирект на /login.

    Если user залогинен, устанавливаем его id в ContextVar — все repo-функции
    внутри запроса автоматически отфильтруют данные по этому пользователю.
    """
    path = request.url.path
    # Текущего user (или None) кладём в request.state для шаблонов ВСЕГДА —
    # чтобы Jinja {{ request.state.current_user }} не падал AttributeError
    # для анонимных запросов на /login и /register.
    user = _current_user(request)
    request.state.current_user = user

    if _is_public(path):
        return await call_next(request)
    if user is None:
        if path.startswith("/api/"):
            return JSONResponse(
                {"ok": False, "error": "Не авторизован"}, status_code=401,
            )
        return RedirectResponse("/login", status_code=302)

    # Устанавливаем user_id в ContextVar — repo-функции автоматически
    # фильтруют данные по этому пользователю. user-объект уже лежит в
    # request.state.current_user (см. начало функции) — для шаблонов.
    token = set_current_user_id(user.id)
    try:
        return await call_next(request)
    finally:
        reset_current_user_id(token)


# SessionMiddleware регистрируется ПОСЛЕ auth_middleware специально:
# в Starlette последний добавленный middleware становится самым внешним,
# поэтому Session отрабатывает первым и кладёт scope["session"],
# а auth_middleware уже может его прочитать.
# SESSION_SECRET берём из env; для dev — дефолт (в prod ОБЯЗАТЕЛЬНО переопределить).
_session_secret = os.environ.get(
    "PUTEVOY_SESSION_SECRET",
    "dev-secret-change-in-production-min-32-chars-long",
)
# Включить флаг Secure на cookie. По умолчанию False (доступ по http://IP),
# при настройке HTTPS-домена выставить PUTEVOY_COOKIE_HTTPS_ONLY=true в .env.
_https_only = os.environ.get("PUTEVOY_COOKIE_HTTPS_ONLY", "").lower() in ("1", "true", "yes")
app.add_middleware(
    SessionMiddleware,
    secret_key=_session_secret,
    session_cookie="putevoy_session",
    max_age=60 * 60 * 24 * 30,  # 30 дней
    same_site="lax",
    https_only=_https_only,
)


# Глобальный helper для шаблонов
templates.env.globals["MONTH_NOMINATIVE_RU"] = MONTH_NOMINATIVE_RU


def _nav_ctx(request: Request | None = None) -> dict:
    vehicles = list_vehicles() if has_profile() else []
    ctx = {
        "has_profile": has_profile(),
        "routes_count": len(list_routes()),
        "runs_count": len(list_runs()),
        "vehicles": vehicles,
        "active_vehicle_id": current_vehicle_id(),
        "current_user": None,
    }
    if request is not None:
        ctx["current_user"] = _current_user(request)
    return ctx


# --- /  →  лендинг (аноним) или кабинет (залогинен) -------------------------

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    # Путь публичный: сюда попадают и анонимы, и залогиненные.
    if request.state.current_user is None:
        return templates.TemplateResponse(request, "landing.html", {})
    # Залогинен — уводим в кабинет; /dashboard сам отправит на /setup,
    # если профиль ещё не настроен (ContextVar там уже выставлен middleware).
    return RedirectResponse("/dashboard", status_code=302)


# --- Auth: register / login / logout ---------------------------------------

@app.get("/register", response_class=HTMLResponse)
async def register_get(request: Request) -> HTMLResponse:
    if _current_user(request):
        return RedirectResponse("/", status_code=302)
    return templates.TemplateResponse(request, "register.html", {})


@app.post("/register")
async def register_post(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    password_confirm: str = Form(...),
    consent: str = Form(default=""),
) -> HTMLResponse:
    email = email.strip().lower()
    errors = []
    if not EMAIL_RE.match(email):
        errors.append("Введите корректный email")
    if len(password) < 8:
        errors.append("Пароль должен быть минимум 8 символов")
    if password != password_confirm:
        errors.append("Пароли не совпадают")
    if consent != "yes":
        errors.append("Необходимо согласие на обработку персональных данных")
    if errors:
        return templates.TemplateResponse(
            request, "register.html", {"errors": errors, "email": email}
        )
    user = create_user(email, password)
    if not user:
        return templates.TemplateResponse(
            request, "register.html",
            {"errors": ["Пользователь с таким email уже зарегистрирован"], "email": email},
        )
    request.session["user_id"] = user.id
    return RedirectResponse("/setup", status_code=303)


@app.get("/login", response_class=HTMLResponse)
async def login_get(request: Request) -> HTMLResponse:
    if _current_user(request):
        return RedirectResponse("/", status_code=302)
    return templates.TemplateResponse(request, "login.html", {})


@app.post("/login")
async def login_post(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
) -> HTMLResponse:
    user = authenticate(email, password)
    if not user:
        return templates.TemplateResponse(
            request, "login.html",
            {"errors": ["Неверный email или пароль"], "email": email.strip()},
        )
    request.session["user_id"] = user.id
    return RedirectResponse("/", status_code=303)


@app.post("/logout")
async def logout_post(request: Request) -> RedirectResponse:
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


# --- /setup -----------------------------------------------------------------

@app.get("/setup", response_class=HTMLResponse)
async def setup_get(request: Request) -> HTMLResponse:
    profile = get_profile()
    # Разбираем существующий базовый адрес ТС на компоненты для предзаполнения
    address_parts = parse_address(profile["vehicle"]["base_address"]) if profile else None
    return templates.TemplateResponse(
        request, "setup.html",
        {**_nav_ctx(), "profile": profile,
         "address_parts": address_parts.to_dict() if address_parts else None,
         "today": date.today().isoformat()},
    )


@app.post("/setup")
async def setup_post(
    organization_name: str = Form(...),
    mechanic_name: str = Form(...),
    driver_full_name: str = Form(...),
    driver_snils: str = Form(...),
    driver_license_number: str = Form(...),
    driver_license_issue_date: str = Form(...),
    vehicle_make_model: str = Form(...),
    vehicle_license_plate: str = Form(...),
    vehicle_fuel_grade: str = Form("АИ-95"),
    vehicle_tank_capacity_l: str = Form("50.0"),
    # Структурированный базовый адрес ТС
    base_city: str = Form(...),
    base_street_type: str = Form(...),
    base_street_name: str = Form(...),
    base_house_number: str = Form(...),
    base_corpus: str = Form(""),
    vehicle_fuel_consumption_l_per_100km: str = Form(...),
    start_odometer_km: int = Form(...),
    start_fuel_balance_l: str = Form(...),
    start_date: str = Form(...),
) -> RedirectResponse:
    vehicle_base_address = compose_address(
        base_city, base_street_type, base_street_name, base_house_number, base_corpus,
    )
    # ВАЖНО: если профиль уже настроен, /setup редактирует ИМЕННО активное ТС
    # (то, что показывалось в форме). Без явного vehicle_id save_setup упал
    # бы на первое ТС по id — и второй автомобиль перезаписал бы первый.
    save_setup(
        organization_name=organization_name, mechanic_name=mechanic_name,
        driver_full_name=driver_full_name, driver_snils=driver_snils,
        driver_license_number=driver_license_number,
        driver_license_issue_date=date.fromisoformat(driver_license_issue_date),
        vehicle_make_model=vehicle_make_model,
        vehicle_license_plate=vehicle_license_plate,
        vehicle_fuel_grade=vehicle_fuel_grade,
        vehicle_tank_capacity_l=_to_float(vehicle_tank_capacity_l),
        vehicle_base_address=vehicle_base_address,
        vehicle_fuel_consumption_l_per_100km=_to_float(vehicle_fuel_consumption_l_per_100km),
        start_odometer_km=start_odometer_km,
        start_fuel_balance_l=_to_float(start_fuel_balance_l),
        start_date=date.fromisoformat(start_date),
        vehicle_id=current_vehicle_id(),
    )
    return RedirectResponse("/routes" if not list_routes() else "/dashboard", status_code=303)


@app.post("/api/calc-distance")
async def api_calc_distance(address: str = Form(...)) -> JSONResponse:
    """Посчитать расстояние от базового адреса до указанного — для UI каталога."""
    profile = get_profile()
    if not profile:
        return JSONResponse({"ok": False, "error": "Профиль не настроен"})
    base = profile["vehicle"]["base_address"]
    result = calc_distance(base, address)
    if isinstance(result, DistanceError):
        return JSONResponse({"ok": False, "error": result.message, "code": result.code})
    return JSONResponse({
        "ok": True,
        "km": result.km,
        "normalized_address": result.normalized_to,
        "source": result.source,
    })


@app.post("/api/import-state")
async def api_import_state(file: UploadFile = File(...)) -> JSONResponse:
    """Прочитать стартовое состояние из загруженного Топливо.xlsx."""
    tmp_path = DOWNLOADS_DIR / f"_import_{file.filename}"
    with tmp_path.open("wb") as f:
        f.write(await file.read())
    try:
        state = import_state_from_xlsx(tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)
    if not state:
        return JSONResponse({"ok": False, "error": "Не удалось распознать файл"})
    return JSONResponse({
        "ok": True,
        "odometer_km": state.odometer_km,
        "fuel_balance_l": state.fuel_balance_l,
        "last_date": state.last_date.isoformat(),
    })


# --- /vehicles --------------------------------------------------------------

@app.get("/vehicles", response_class=HTMLResponse)
async def vehicles_get(request: Request) -> HTMLResponse:
    if not has_profile():
        return RedirectResponse("/setup", status_code=302)
    vehicles = list_vehicles()
    # Состояния каждого ТС — чтобы показать в таблице
    states = {v.id: get_vehicle_state(v.id) for v in vehicles}
    return templates.TemplateResponse(
        request, "vehicles.html",
        {**_nav_ctx(), "vehicles_full": vehicles, "states": states,
         "today": date.today().isoformat()},
    )


@app.post("/vehicles/add")
async def vehicles_add(
    make_model: str = Form(...),
    license_plate: str = Form(...),
    fuel_grade: str = Form("АИ-95"),
    tank_capacity_l: str = Form("50"),
    base_address: str = Form(...),
    fuel_consumption_l_per_100km: str = Form(...),
    start_odometer_km: int = Form(...),
    start_fuel_balance_l: str = Form(...),
    start_date: str = Form(...),
) -> RedirectResponse:
    new_id = add_vehicle(
        make_model=make_model, license_plate=license_plate,
        fuel_grade=fuel_grade,
        tank_capacity_l=_to_float(tank_capacity_l),
        base_address=base_address,
        fuel_consumption_l_per_100km=_to_float(fuel_consumption_l_per_100km),
        start_odometer_km=start_odometer_km,
        start_fuel_balance_l=_to_float(start_fuel_balance_l),
        start_date=date.fromisoformat(start_date),
    )
    set_active_vehicle(new_id)
    return RedirectResponse("/vehicles", status_code=303)


@app.post("/vehicles/{vehicle_id}/update")
async def vehicles_update(
    vehicle_id: int,
    make_model: str = Form(...),
    license_plate: str = Form(...),
    fuel_grade: str = Form("АИ-95"),
    tank_capacity_l: str = Form("50"),
    base_address: str = Form(...),
    fuel_consumption_l_per_100km: str = Form(...),
    current_odometer_km: int = Form(...),
    current_fuel_balance_l: str = Form(...),
    last_date: str = Form(...),
) -> RedirectResponse:
    update_vehicle(
        vehicle_id=vehicle_id,
        make_model=make_model, license_plate=license_plate,
        fuel_grade=fuel_grade,
        tank_capacity_l=_to_float(tank_capacity_l),
        base_address=base_address,
        fuel_consumption_l_per_100km=_to_float(fuel_consumption_l_per_100km),
    )
    update_vehicle_state(
        vehicle_id=vehicle_id,
        current_odometer_km=current_odometer_km,
        current_fuel_balance_l=_to_float(current_fuel_balance_l),
        last_date=date.fromisoformat(last_date),
    )
    return RedirectResponse("/vehicles", status_code=303)


@app.post("/vehicles/{vehicle_id}/delete")
async def vehicles_delete(vehicle_id: int) -> RedirectResponse:
    delete_vehicle(vehicle_id)
    return RedirectResponse("/vehicles", status_code=303)


@app.post("/vehicles/switch/{vehicle_id}")
async def vehicles_switch(vehicle_id: int, request: Request) -> RedirectResponse:
    """Переключить активное ТС. Редирект туда, откуда пришёл запрос."""
    set_active_vehicle(vehicle_id)
    referer = request.headers.get("referer", "/dashboard")
    return RedirectResponse(referer, status_code=303)


# --- /routes ----------------------------------------------------------------

@app.get("/routes", response_class=HTMLResponse)
async def routes_get(request: Request) -> HTMLResponse:
    if not has_profile():
        return RedirectResponse("/setup", status_code=302)
    profile = get_profile()
    routes = list_routes()
    return templates.TemplateResponse(
        request, "routes.html",
        {**_nav_ctx(), "routes": routes, "profile": profile},
    )


def _compose_address(
    street_type: str, street_name: str,
    house_number: str, corpus: str, base_address: str,
) -> str:
    """Собрать адрес из структурированных частей в формат, понятный геокодеру.

    Пример: «Санкт-Петербург, улица Репищева 10к3»
    Город берётся из первого сегмента base_address ТС (до первой запятой).
    """
    city = base_address.split(",")[0].strip() if base_address else ""
    house = house_number.strip()
    if corpus.strip():
        house += "к" + corpus.strip()
    street_part = f"{street_type} {street_name.strip()} {house}".strip()
    return f"{city}, {street_part}" if city else street_part


@app.post("/routes/add")
async def routes_add(
    km_one_way: str = Form(...),
    weight: str = Form(...),
    # Структурированные поля — основной путь из формы UI
    street_type: str = Form(""),
    street_name: str = Form(""),
    house_number: str = Form(""),
    corpus: str = Form(""),
    # Backward-compat: можно передать одну строку «address»
    address: str = Form(""),
    is_large: bool = Form(False),
) -> RedirectResponse:
    if street_name and house_number:
        profile = get_profile()
        base = profile["vehicle"]["base_address"] if profile else ""
        final = _compose_address(street_type or "улица", street_name, house_number, corpus, base)
    elif address:
        final = address
    else:
        raise HTTPException(400, "Не указан ни структурированный адрес, ни поле address")
    add_route(address=final, km_one_way=_to_float(km_one_way),
              is_large=is_large, weight=_to_float(weight))
    return RedirectResponse("/routes", status_code=303)


@app.post("/api/compose-address")
async def api_compose_address(
    street_type: str = Form(...),
    street_name: str = Form(...),
    house_number: str = Form(...),
    corpus: str = Form(""),
) -> JSONResponse:
    """Вспомогательный endpoint для UI: собрать адрес из частей для предпросмотра/геокодинга."""
    profile = get_profile()
    base = profile["vehicle"]["base_address"] if profile else ""
    address = _compose_address(street_type, street_name, house_number, corpus, base)
    return JSONResponse({"address": address})


@app.post("/routes/{route_id}/delete")
async def routes_delete(route_id: int) -> RedirectResponse:
    delete_route(route_id)
    return RedirectResponse("/routes", status_code=303)


@app.post("/routes/{route_id}/update")
async def routes_update(
    route_id: int,
    address: str = Form(...),
    km_one_way: str = Form(...),
    weight: str = Form(...),
    is_large: bool = Form(False),
) -> RedirectResponse:
    update_route(route_id, address=address, km_one_way=_to_float(km_one_way),
                 is_large=is_large, weight=_to_float(weight))
    return RedirectResponse("/routes", status_code=303)


# --- /dashboard -------------------------------------------------------------

def _suggest_next_month() -> tuple[int, int]:
    """Подсказать следующий месяц для генерации.

    Логика по приоритету:
      1. Если есть прогоны → месяц, следующий за самым свежим.
      2. Если профиль настроен → месяц, следующий за state.last_date.
         (т.е. user ввёл «состояние на конец мая» → предлагаем июнь).
      3. Иначе → предыдущий календарный (новый user без профиля).
    """
    runs = list_runs()
    if runs:
        latest = max(runs, key=lambda r: (r.year, r.month))
        y, m = latest.year, latest.month
    else:
        prof = get_profile()
        if prof and prof.get("state") and prof["state"].get("last_date"):
            ld = prof["state"]["last_date"]
            y, m = ld.year, ld.month
        else:
            today = date.today()
            pm = today.month - 1 if today.month > 1 else 12
            py = today.year if today.month > 1 else today.year - 1
            return py, pm
    nm = m + 1 if m < 12 else 1
    ny = y if m < 12 else y + 1
    return ny, nm


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request) -> HTMLResponse:
    if not has_profile():
        return RedirectResponse("/setup", status_code=302)
    profile = get_profile()
    runs = list_runs()
    next_year, next_month = _suggest_next_month()
    return templates.TemplateResponse(
        request, "dashboard.html",
        {**_nav_ctx(), "profile": profile, "runs": runs,
         "next_month": next_month, "next_year": next_year},
    )


# --- /generate --------------------------------------------------------------

@app.get("/generate", response_class=HTMLResponse)
async def generate_get(
    request: Request,
    year: int = date.today().year,
    month: Optional[int] = None,
) -> HTMLResponse:
    if not has_profile():
        return RedirectResponse("/setup", status_code=302)
    profile = get_profile()
    if month is None:
        suggested_year, suggested_month = _suggest_next_month()
        year, month = suggested_year, suggested_month
    wd = working_days(year, month)
    existing_fuelings = get_existing_fuelings(year, month)
    existing_skip_dates = get_existing_skip_dates(year, month)
    from ..storage.repo import get_run as repo_get_run
    import json as _json
    existing_run = repo_get_run(year, month)
    previous_issues = None
    if existing_run and existing_run.validation_report_json:
        try:
            previous_issues = _json.loads(existing_run.validation_report_json)
        except Exception:
            previous_issues = None
    # Список годов для селектора: ±3 от текущего, плюс гарантия что выбранный год в списке
    today_year = date.today().year
    years_range = list(range(today_year - 3, today_year + 2))
    if year not in years_range:
        years_range.append(year)
        years_range.sort()
    return templates.TemplateResponse(
        request, "generate.html",
        {**_nav_ctx(), "profile": profile,
         "year": year, "month": month,
         "month_name": MONTH_NOMINATIVE_RU[month],
         "working_days_count": len(wd),
         "working_days_iso": [d.isoformat() for d in wd],
         "months": [(m, MONTH_NOMINATIVE_RU[m]) for m in range(1, 13)],
         "years_range": years_range,
         "existing_fuelings": existing_fuelings,
         "existing_skip_dates": [d.isoformat() for d in existing_skip_dates],
         "existing_run": existing_run,
         "previous_issues": previous_issues},
    )


@app.post("/api/preview-generate")
async def api_preview_generate(
    year: int = Form(...),
    month: int = Form(...),
    fueling_date: list[str] = Form(default=[]),
    fueling_liters: list[str] = Form(default=[]),
    fueling_price: list[str] = Form(default=[]),
    skip_date: list[str] = Form(default=[]),
) -> JSONResponse:
    """Прогнать генерацию без сохранения — для интерактивного UI «дни простоя»."""
    if not has_profile():
        return JSONResponse({"ok": False, "error": "Профиль не настроен"})
    fuelings = _parse_fueling_form(fueling_date, fueling_liters, fueling_price, "", year)
    skip_dates = _parse_skip_dates(skip_date)
    try:
        result, report = preview_run(year, month, fuelings, skip_dates=skip_dates)
    except RuntimeError as e:
        return JSONResponse({"ok": False, "error": str(e)})
    out = result.output
    fuel_neg = [i for i in report.issues if i.code == "FUEL_NEGATIVE"]
    tank_over = [i for i in report.issues if i.code == "TANK_OVERFLOW"]
    # Минимальный остаток за месяц — самая полезная метрика
    min_balance = min((d.fuel_balance_end for d in out.days), default=0.0)
    return JSONResponse({
        "ok": report.ok,
        "valid": report.ok,
        "days_count": len(out.days),
        "final_balance_l": round(out.final_state.last_fuel_balance_l, 2),
        "min_balance_l": round(min_balance, 2),
        "fuel_negative_count": len(fuel_neg),
        "tank_overflow_count": len(tank_over),
        "first_issues": [i.message for i in report.issues[:5]],
    })


@app.post("/api/parse-fuelings")
async def api_parse_fuelings(
    text: str = Form(...),
    year: int = Form(...),
) -> JSONResponse:
    parsed = parse_fuelings(text, default_year=year)
    return JSONResponse([
        {"date": f.date.isoformat(), "liters": f.liters, "price_per_l": f.price_per_l,
         "sum": f.sum or round(f.liters * f.price_per_l, 2)}
        for f in parsed
    ])


def _parse_fueling_form(fueling_date, fueling_liters, fueling_price,
                        fuelings_text: str, year: int) -> list[Fueling]:
    fuelings: list[Fueling] = []
    for d_str, l_str, p_str in zip(fueling_date, fueling_liters, fueling_price):
        if not (d_str and l_str and p_str):
            continue
        try:
            fuelings.append(Fueling(
                date=date.fromisoformat(d_str),
                liters=float(l_str.replace(",", ".")),
                price_per_l=float(p_str.replace(",", ".")),
            ))
        except (ValueError, TypeError):
            continue
    if not fuelings and fuelings_text:
        fuelings = parse_fuelings(fuelings_text, default_year=year)
    return fuelings


def _parse_skip_dates(skip_date: list[str]) -> list[date]:
    result: list[date] = []
    for s in skip_date or []:
        if not s:
            continue
        try:
            result.append(date.fromisoformat(s))
        except ValueError:
            continue
    return result


@app.post("/generate", response_class=HTMLResponse)
async def generate_post(
    request: Request,
    year: int = Form(...),
    month: int = Form(...),
    fueling_date: list[str] = Form(default=[]),
    fueling_liters: list[str] = Form(default=[]),
    fueling_price: list[str] = Form(default=[]),
    skip_date: list[str] = Form(default=[]),
    fuelings_text: str = Form(default=""),
) -> HTMLResponse:
    if not has_profile():
        return RedirectResponse("/setup", status_code=302)

    fuelings = _parse_fueling_form(fueling_date, fueling_liters, fueling_price,
                                   fuelings_text, year)
    skip_dates = _parse_skip_dates(skip_date)

    try:
        result, report = run_and_persist(year, month, fuelings, skip_dates=skip_dates)
    except RuntimeError as e:
        raise HTTPException(400, str(e))

    out = result.output
    return templates.TemplateResponse(
        request, "generate_result.html",
        {**_nav_ctx(),
         "year": year, "month": month,
         "month_name": MONTH_NOMINATIVE_RU[month],
         "days_count": len(out.days),
         "seed_used": result.seed_used, "seed_attempts": result.attempts,
         "final_odometer": out.final_state.last_odometer_km,
         "final_balance": round(out.final_state.last_fuel_balance_l, 2),
         "report": report,
         "fuelings_count": len(out.input.fuelings),
         "valid": report.ok},
    )


@app.post("/generate/{year}/{month}/delete")
async def generate_delete(year: int, month: int, request: Request) -> RedirectResponse:
    """Удалить ранее сгенерированный месяц."""
    delete_run(year, month)
    # Возвращаемся туда, откуда пришёл запрос (Обзор или История)
    referer = request.headers.get("referer", "/dashboard")
    return RedirectResponse(referer, status_code=303)


# --- /history ---------------------------------------------------------------

@app.get("/history", response_class=HTMLResponse)
async def history(request: Request) -> HTMLResponse:
    if not has_profile():
        return RedirectResponse("/setup", status_code=302)
    runs = list_runs()
    return templates.TemplateResponse(
        request, "history.html",
        {**_nav_ctx(), "runs": runs},
    )


# --- /download/... ----------------------------------------------------------

@app.get("/download/waybill/{year}/{month}")
async def download_waybill(year: int, month: int) -> FileResponse:
    out_dir = DOWNLOADS_DIR / f"{year}-{month:02d}"
    p = write_waybill_for_run(year, month, out_dir)
    if not p:
        raise HTTPException(404, "Прогон не найден")
    return FileResponse(p, filename=p.name,
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.get("/download/fuel-month/{year}/{month}")
async def download_fuel_month(year: int, month: int) -> FileResponse:
    out_dir = DOWNLOADS_DIR / f"{year}-{month:02d}"
    p = write_fuel_log_for_month(year, month, out_dir)
    if not p:
        raise HTTPException(404, "Прогон не найден")
    return FileResponse(p, filename=p.name,
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.get("/download/fuel-full")
async def download_fuel_full() -> FileResponse:
    out_dir = DOWNLOADS_DIR / "full"
    p = write_full_fuel_log(out_dir)
    if not p:
        raise HTTPException(404, "Нет прогонов")
    return FileResponse(p, filename=p.name,
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# --- PDF превью ------------------------------------------------------------

@app.get("/preview/waybill/{year}/{month}")
async def preview_waybill(year: int, month: int) -> FileResponse:
    """PDF-превью путевых листов для просмотра в браузере.

    Конвертирует свежесгенерированный xlsx в pdf через LibreOffice.
    Если LibreOffice не установлен — возвращает 503 с сообщением.
    """
    from urllib.parse import quote
    from .pdf_preview import xlsx_to_pdf
    out_dir = DOWNLOADS_DIR / f"{year}-{month:02d}"
    xlsx = write_waybill_for_run(year, month, out_dir)
    if not xlsx:
        raise HTTPException(404, "Прогон не найден")
    result = xlsx_to_pdf(xlsx, out_dir / "pdf")
    if result.error:
        raise HTTPException(503, result.error)
    # RFC 5987: filename с не-Latin-1 символами кодируется как filename*=UTF-8''<percent-encoded>.
    # Это позволяет браузерам корректно показать русское имя файла при сохранении.
    encoded_name = quote(result.pdf_path.name, safe="")
    return FileResponse(
        result.pdf_path,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"inline; filename*=UTF-8''{encoded_name}",
        },
    )
