# Деплой Путевой.AI на VPS

Инструкция для первичного деплоя на сервер TimeWeb VibeCoder (`72.56.39.144`).

---

## Предусловия (уже выполнено)

Сервер подготовлен в прошлой сессии:

- ✅ Ubuntu 24.04 LTS, 1 vCPU / 1 GB RAM / 15 GB NVMe
- ✅ Swap 2 GB (`/swapfile`, swappiness=10)
- ✅ Docker 29.5.3 + Compose v5.1.4, автозапуск
- ✅ SSH-ключ `~/.ssh/putevoy_deploy` авторизован для root
- ✅ Старый бот `tgbot-rashod` снесён, БД забэкаплена

Команда подключения:

```bash
ssh -i ~/.ssh/putevoy_deploy root@72.56.39.144
```

---

## Первый деплой (с локальной Windows-машины)

### 1. Сгенерировать сессионный секрет

На локальной машине:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Скопировать вывод — это значение `PUTEVOY_SESSION_SECRET`.

### 2. Залить код на сервер

С локальной машины через `scp` (Windows OpenSSH работает из PowerShell):

```powershell
# Создать папку на сервере и залить код
ssh -i ~\.ssh\putevoy_deploy root@72.56.39.144 "mkdir -p /opt/putevoy"

# rsync если установлен — быстрее. Иначе scp.
# scp -r (рекурсивно) с исключением мусора
scp -i ~\.ssh\putevoy_deploy -r `
    src `
    pyproject.toml `
    Dockerfile `
    docker-compose.yml `
    .dockerignore `
    .env.example `
    root@72.56.39.144:/opt/putevoy/
```

Альтернатива через WSL с `rsync`:

```bash
rsync -avz --exclude='.venv' --exclude='__pycache__' --exclude='data' \
      --exclude='tests' --exclude='_server_backups' \
      -e "ssh -i ~/.ssh/putevoy_deploy" \
      ./ root@72.56.39.144:/opt/putevoy/
```

### 3. Настроить `.env` на сервере

Подключиться:

```bash
ssh -i ~/.ssh/putevoy_deploy root@72.56.39.144
cd /opt/putevoy
```

Создать `.env`:

```bash
cp .env.example .env
nano .env
```

Вставить туда сгенерированный секрет:

```
PUTEVOY_SESSION_SECRET=<сюда вставьте вывод token_urlsafe(48)>
YANDEX_GEOCODER_API_KEY=
```

Сохранить (Ctrl+O, Enter, Ctrl+X).

### 4. Билд и запуск

```bash
docker compose up -d --build
```

Первый билд ≈ 5–8 минут (тянется LibreOffice ~600 MB). Образ собирается с кешем —
повторные билды после правок кода будут быстрыми (≈ 30 секунд).

Логи:

```bash
docker compose logs -f web
```

Проверить что контейнер живёт:

```bash
docker compose ps
```

Должно показать `putevoy` в статусе `Up` (и `healthy` через ~30 секунд).

### 5. Проверка

С локальной машины — открыть в браузере:

```
http://72.56.39.144:8000/login
```

Должна открыться страница входа. Зарегистрироваться, ввести профиль, сгенерировать тестовый месяц.

---

## Обновление кода (последующие деплои)

Когда внесли правки локально:

```powershell
# Перелить только то что изменилось
scp -i ~\.ssh\putevoy_deploy -r src root@72.56.39.144:/opt/putevoy/

# На сервере: пересобрать образ и перезапустить
ssh -i ~\.ssh\putevoy_deploy root@72.56.39.144 "cd /opt/putevoy && docker compose up -d --build"
```

Простой даунтайм < 5 секунд (Docker делает rolling restart с healthcheck).

---

## Бэкап БД

Volume `putevoy_data` содержит SQLite-файл и переживает перезапуски, но не диск-фейл.
Регулярный бэкап:

```bash
ssh -i ~/.ssh/putevoy_deploy root@72.56.39.144 bash <<'EOF'
mkdir -p /opt/backups
ts=$(date +%Y%m%d_%H%M%S)
docker run --rm \
    -v putevoy_data:/data \
    -v /opt/backups:/backup \
    alpine tar czf /backup/putevoy_data_${ts}.tar.gz -C /data .
ls -la /opt/backups | tail -5
EOF
```

Скачать бэкап локально:

```powershell
scp -i ~\.ssh\putevoy_deploy root@72.56.39.144:/opt/backups/putevoy_data_*.tar.gz .
```

Восстановление (если что):

```bash
docker compose down
docker run --rm -v putevoy_data:/data -v $(pwd):/backup \
    alpine sh -c "rm -rf /data/* && tar xzf /backup/putevoy_data_YYYYMMDD_HHMMSS.tar.gz -C /data"
docker compose up -d
```

---

## Откат при проблеме

Если новый билд сломал прод:

```bash
# Посмотреть предыдущие образы
docker images putevoy*

# Откатиться на предыдущий тэг (если был тэгирован) или быстро — git
cd /opt/putevoy
# вернуть src к предыдущей версии (если использовали git)
docker compose up -d --build
```

Пока используем scp без git — простейший откат: на локальной машине сделать
`git checkout <предыдущий_коммит>` и снова scp.

---

## После регистрации домена (HTTPS)

Когда зарегистрируешь домен (рекомендация — `putevoylist.ru` или `moiputevoy.ru`):

1. В DNS-панели 2domains.ru указать A-запись: `@` → `72.56.39.144`, `www` → `72.56.39.144`.
2. На сервере добавить Caddy как reverse proxy с автоматическим Let's Encrypt:
   ```yaml
   # дописать в docker-compose.yml
   caddy:
     image: caddy:2-alpine
     restart: unless-stopped
     ports:
       - "80:80"
       - "443:443"
     volumes:
       - ./Caddyfile:/etc/caddy/Caddyfile
       - caddy_data:/data
       - caddy_config:/config
   ```
3. `Caddyfile`:
   ```
   putevoylist.ru, www.putevoylist.ru {
       reverse_proxy web:8000
   }
   ```
4. В `.env` добавить `PUTEVOY_COOKIE_HTTPS_ONLY=true` (надо будет вынести флаг в env-переменную в `app.py`).
5. Убрать публикацию `8000:8000` из `docker-compose.yml` — наружу только 80/443 через Caddy.

---

## Что наблюдать после запуска

- `docker compose logs -f web` — нет ли крешей при первой регистрации
- `docker stats putevoy` — RAM в норме? Должно быть < 400 MB в покое
- `free -h` на сервере — swap не должен активно использоваться (если используется > 500 MB постоянно — значит RAM не хватает)
- При первой генерации с PDF превью — LibreOffice может занять ~500 MB на момент конвертации. Это нормально.

---

## Полезные команды

```bash
# Зайти внутрь контейнера
docker compose exec web bash

# Посмотреть размер volumes
docker system df -v | grep putevoy

# Очистить старые образы (после нескольких обновлений)
docker image prune -f

# Полный рестарт без пересборки
docker compose restart web

# Стоп и удаление (БД остаётся в volume)
docker compose down

# СТОП И УДАЛЕНИЕ ДАННЫХ (опасно!)
docker compose down -v   # минусы данные нельзя восстановить без бэкапа
```
