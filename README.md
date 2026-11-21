# Keitaro wrapper

[![CI](https://github.com/DiMiRka/etolegko-keitaro/actions/workflows/ci.yml/badge.svg?branch=master)](https://github.com/DiMiRka/etolegko-keitaro/actions/workflows/ci.yml)

Обёртка над [Keitaro](https://keitaro.io) Admin API: создание кампаний по шаблону и редактор офферов в потоках с отложенной публикацией.

- **Создаватор кампаний.** Имя, гео и оффер превращаются в кампанию с двумя потоками: поток 1 отправляет трафик из указанной страны на `https://google.com`, поток 2 отправляет всех остальных на выбранный оффер. Домен, группа и источник выбираются из списков Keitaro (по умолчанию значения из настроек). Ротация «по позиции» и CPC 0 USD ставятся всегда.
- **Редактор потоков.** Fetch забирает потоки из Keitaro. Офферы можно добавлять, удалять (removed, с кнопкой Bring back) и закреплять их долю. Веса пересчитываются сразу, поток подсвечивается жёлтым, пока изменения не опубликованы. Push to KT публикует поток, Cancel откатывает несохранённые изменения. Перед публикацией сервис проверяет, не изменили ли поток прямо в Keitaro после загрузки, и не перезаписывает чужие изменения без подтверждения.
- **Список и карточка кампании.** В списке есть поиск, фильтры по группе и состоянию, клики и конверсии за 7 дней. В карточке видна ссылка кампании для трафика (домен + alias) с копированием, кампанию можно включить или выключить. Настройки разложены по вкладкам, как в Keitaro: «Общие» (имя, гео, домен, группа, источник), «Затраты» (модель, стоимость, валюта, стоимость из параметра cost, % потерь), «Уникальность» (метод, срок, параметр, cookies) и «Заметки». Ротация потоков показывается, но не меняется: создаватор и логика потоков рассчитаны на ротацию «по позиции». Параметры источника и S2S-постбэки остаются в Keitaro, туда ведёт кнопка «Открыть в Keitaro».
- **Офферы.** Каталог офферов Keitaro с поиском и карточка оффера: параметры, статистика за 7 дней по всему трекеру и список потоков кампаний сервиса, где он стоит. Только просмотр: у API-ключа нет прав на создание и изменение офферов.

Стек: FastAPI, SQLAlchemy 2.0 (async), Alembic, httpx, pydantic-settings, Jinja2 + jQuery + Select2. Тесты на `unittest`.

## Запуск в Docker

Нужен Docker с Compose v2.

```powershell
copy .env.example .env            # Linux/macOS: cp .env.example .env
```

Впишите в `.env` значение `KEITARO_API_KEY` (в админке Keitaro: Профиль → API ключи), а также `SECRET_KEY`, `ADMIN_USERNAME` и `ADMIN_PASSWORD` для входа в сервис (см. «Пользователи и вход»). Затем:

```powershell
docker compose up -d --build
```

Поднимутся PostgreSQL и приложение. При старте контейнер приложения сам применяет миграции (`alembic upgrade head`) и, если пользователей ещё нет, создаёт первого из `ADMIN_USERNAME` и `ADMIN_PASSWORD`. Интерфейс откроется на http://localhost:8000, документация API на http://localhost:8000/docs. `DATABASE_URL` из `.env` внутри Docker не используется: приложение подключается к сервису `db`.

Если порты 8000 или 5432 заняты, задайте другие:

```powershell
$env:APP_PORT=8080; $env:POSTGRES_PORT=5433; docker compose up -d --build
```

В Linux/macOS: `APP_PORT=8080 POSTGRES_PORT=5433 docker compose up -d --build`.

Логи и остановка:

```powershell
docker compose logs -f app
docker compose down            # данные базы остаются в volume pgdata
docker compose down -v         # удалить и данные
```

## Быстрый старт без Docker (SQLite)

Нужен Python 3.12+.

```powershell
python -m venv .venv
.venv\Scripts\activate            # Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env            # Linux/macOS: cp .env.example .env
```

Заполните в `.env` ключ API: в админке Keitaro откройте Профиль → API ключи.

```env
KEITARO_URL=https://tlgk.host
KEITARO_API_KEY=ваш_ключ
```

Примените миграции, создайте пользователя и запустите приложение:

```powershell
alembic upgrade head
python -m app.cli create-user admin
uvicorn app.main:app --reload
```

Приложение откроется на http://localhost:8000, документация API на http://localhost:8000/docs (тоже после входа).

## Пользователи и вход

Все страницы и API доступны только после входа. Неавторизованного пользователя страницы перенаправляют на `/login?next=…` и после входа возвращают туда, откуда он пришёл. API без входа отвечает `401`. Открыты только `/login`, `/health` и статика.

- Пароли хранятся в виде хеша scrypt с солью. Сессия хранится в cookie `kw_session`, подписанной HMAC-SHA256 ключом `SECRET_KEY` (HttpOnly, SameSite=Lax, срок `SESSION_TTL_HOURS`). Если `SECRET_KEY` не задан, ключ генерируется при старте, и после перезапуска придётся войти заново.
- Первый пользователь создаётся при старте из `ADMIN_USERNAME` и `ADMIN_PASSWORD`, если в базе ещё нет ни одного пользователя. Остальные создаются командами:

```powershell
python -m app.cli create-user ivan          # пароль спросит в терминале
python -m app.cli set-password ivan
docker compose exec app python -m app.cli create-user ivan   # то же в Docker
```

- В журнале изменений у каждой записи указан пользователь, который выполнил действие.

## Локальный запуск с PostgreSQL из Docker

Можно поднять в Docker только базу, а приложение запускать локально:

```powershell
docker compose up -d db
```

Если порт 5432 уже занят, задайте другой через `POSTGRES_PORT` (например `$env:POSTGRES_PORT=5433`, в Linux/macOS `POSTGRES_PORT=5433 docker compose up -d db`) и укажите тот же порт в `DATABASE_URL`.

В `.env` замените строку подключения:

```env
DATABASE_URL=postgresql+asyncpg://keitaro:keitaro@localhost:5432/keitaro
```

Дальше те же `alembic upgrade head` и `uvicorn app.main:app --reload`.

## Миграции

Alembic берёт адрес базы из `DATABASE_URL`, это же значение использует приложение.

```powershell
alembic upgrade head                                  # применить все
alembic downgrade -1                                  # откатить последнюю
alembic revision --autogenerate -m "описание"         # новая миграция после изменения app/models.py
```

## Тесты

```powershell
pip install -r requirements-dev.txt
python -m unittest discover -s tests
ruff check .
```

Тестам не нужны ни сеть, ни `.env`. Keitaro подменяется фейковым клиентом или `httpx.MockTransport`, база берётся SQLite в памяти.

На каждый push GitHub Actions ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)) прогоняет ruff и тесты, применяет миграции на PostgreSQL вверх, вниз и снова вверх и собирает Docker-образ.

## Настройки

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `KEITARO_URL` | `https://tlgk.host` | адрес трекера, путь `/admin_api/v1` клиент добавляет сам |
| `KEITARO_API_KEY` | — | ключ Admin API |
| `DATABASE_URL` | `sqlite+aiosqlite:///./app.db` | база приложения |
| `KEITARO_TIMEZONE` | `Europe/Moscow` | часовой пояс отчётов: границы дней и «сегодня» |
| `SECRET_KEY` | случайный при старте | ключ подписи cookie сессии |
| `SESSION_TTL_HOURS` | `168` | сколько часов действует вход |
| `COOKIE_SECURE` | `false` | `true`, если сервис открыт по https |
| `ADMIN_USERNAME`, `ADMIN_PASSWORD` | — | первый пользователь, создаётся при старте, если пользователей нет |
| `CAMPAIGN_PREFIX` | `test_mironov_` | префикс имени новой кампании |
| `KEITARO_DOMAIN_ID` | `1813` | домен, выбранный в форме создания по умолчанию |
| `KEITARO_GROUP_ID` | `10332` | группа по умолчанию (FORTESTS) |
| `KEITARO_TRAFFIC_SOURCE_ID` | `836` | источник по умолчанию (FORTESTS) |

## Как это работает

### Состояние оффера в потоке

У каждого оффера в потоке хранятся рабочие поля (`share`, `state`: `active` или `removed`) и снимок последней публикации (`published_share`, `published_state`). Поток жёлтый, если хотя бы у одного оффера рабочие поля отличаются от снимка. Отдельного флага «грязный» нет, он вычисляется.

```mermaid
stateDiagram-v2
    direction LR
    state "Новый" as fresh
    state "Активен" as active
    state "Удалён" as removing
    state "Архив" as archived
    [*] --> fresh: Add
    fresh --> active: Push
    fresh --> [*]: Remove или Cancel
    active --> active: пересчёт доли при Add, Pin, Bring back
    active --> removing: Remove
    removing --> active: Bring back или Cancel
    removing --> archived: Push
    archived --> active: Bring back и Push
    active --> archived: Fetch, если оффер удалили в Keitaro
```

«Новый» — оффер без снимка (ещё не был в Keitaro). «Удалён» — снят локально, но в Keitaro ещё есть. «Архив» — `removed` и в рабочих полях, и в снимке: оффера нет в Keitaro, но он остаётся у нас серым с кнопкой Bring back. Cancel возвращает любой оффер к состоянию снимка.

| Действие | Что происходит |
|---|---|
| **Fetch** | Потоки обновляются по `stream_id`, удалённые в Keitaro потоки удаляются у нас. Доли берутся из Keitaro как есть. Оффер, которого больше нет в Keitaro, становится `removed` с долей 0 и кнопкой Bring back. Неопубликованные изменения сбрасываются к состоянию Keitaro, пины сохраняются. Поток без офферов (например редирект с фильтром) сохраняется просто как поток, его содержимое не разбирается. |
| **Add** | Оффер добавляется без снимка, веса пересчитываются. Если оффер уже лежит в архиве, он возвращается (Bring back). |
| **Remove** | Опубликованный оффер становится `removed` с долей 0 и остаётся в архиве. Ещё не опубликованный оффер просто удаляется. |
| **Bring back** | Оффер снова `active`, веса пересчитываются. |
| **Pin** | Доля закрепляется: текущая или заданная вручную. |
| **Cancel** | Офферы без снимка удаляются, остальным возвращаются доля и статус из снимка. |
| **Push** | В `PUT /streams/{id}` уходит список активных офферов с долями (Keitaro заменяет список целиком). После успеха снимок приравнивается к рабочим полям. При ошибке поток остаётся жёлтым, текст ошибки сохраняется. |
| **Защита от конфликтов** | Перед Push поток перечитывается из Keitaro и сравнивается со снимком. Если с момента загрузки офферы в Keitaro изменили (другая доля, оффер удалён, добавлен или отключён), публикация останавливается с ответом `409` и списком изменений, а в журнал пишется «Конфликт». Дальше можно загрузить потоки заново или опубликовать с перезаписью (`?force=true`, в интерфейсе после подтверждения). |

### Пересчёт весов

- Закреплённые офферы сохраняют долю.
- Остаток `100 − сумма закреплённых` делится поровну между активными незакреплёнными. Проценты целые, лишние единицы достаются первым по порядку (34 / 33 / 33).
- Удалённые офферы получают 0.
- Сумма активных всегда ровно 100. Если это невозможно (закреплённые в сумме больше 100, или закреплены все активные, но в сумме не 100), операция отклоняется с понятной ошибкой и ничего не меняет.

Keitaro сам сумму долей не проверяет (принимает и 99), поэтому проверка выполняется на нашей стороне перед Push.

### Статистика

В карточке кампании показана статистика за последние 7 дней, включая сегодня, в часовом поясе `KEITARO_TIMEZONE`: клики, уникальные клики, конверсии, CR, доход и график кликов по дням. У каждого потока указаны клики, уникальные клики и боты за сегодня, а также клики за период. У каждого оффера показаны клики и тренд по дням.

### Журнал изменений и состояние потоков

Каждое действие в сервисе записывается в журнал кампании: создание, подключение, изменение полей, включение и выключение кампании и потоков, загрузка потоков, добавление, удаление, возврат и закрепление офферов, отмена, публикация и ошибки публикации. Для операций с офферами сохраняются доли до и после. При загрузке потоков в журнал попадает и синхронизация: какие офферы удалили или добавили прямо в Keitaro и какие неопубликованные изменения были сброшены.

Поток можно выключить и включить из карточки (`POST /streams/{id}/disable|enable` в Keitaro). Выключенный поток остаётся в списке и показывается приглушённым. Всё это собирается одним запросом `POST /report/build` с разбивкой по `stream_id`, `offer_id` и `day` и фильтром по кампании. Дни без кликов показываются нулями.

## API

| Метод | Путь | Описание |
|---|---|---|
| GET | `/api/offers?q=` | поиск офферов Keitaro по имени или ID для автокомплита (кэш 60 с) |
| GET | `/api/offers/catalog` | все офферы с кликами за 7 дней и числом кампаний сервиса, где оффер активен |
| GET | `/api/offers/{id}` | оффер и его использование в потоках кампаний сервиса |
| GET | `/api/offers/{id}/stats?days=7` | статистика оффера по всему трекеру и топ кампаний по кликам |
| GET | `/api/campaigns` | кампании в базе сервиса: состояние, группа, ссылка |
| GET | `/api/campaigns/stats?days=7` | клики, конверсии и доход по всем кампаниям списка одним запросом отчёта |
| POST | `/api/campaigns/{id}/state` | включить или выключить кампанию в Keitaro `{active}` |
| GET | `/api/campaigns/{id}/log` | журнал изменений кампании, последние 100 записей |
| GET | `/api/campaigns/{id}/settings` | затраты, уникальность, заметки и ротация кампании, читаются из Keitaro |
| PATCH | `/api/campaigns/{id}/settings` | изменить затраты, уникальность и заметки, отправляются только изменённые поля |
| POST | `/api/streams/{id}/state` | включить или выключить поток в Keitaro `{active}` |
| POST | `/api/groups` | создать группу кампаний в Keitaro `{name}`, префикс `test_mironov_` подставляется сам |
| GET | `/api/references` | домены, группы кампаний и источники из Keitaro (кэш 5 мин) и значения по умолчанию |
| POST | `/api/campaigns` | создать кампанию `{name, geo, offer_id, domain_id?, group_id?, traffic_source_id?}` |
| POST | `/api/campaigns/import` | подключить существующую кампанию `{keitaro_id}` |
| GET | `/api/campaigns/{id}` | кампания с потоками и офферами |
| PATCH | `/api/campaigns/{id}` | изменить `{name?, geo?, domain_id?, group_id?, traffic_source_id?}` сразу в Keitaro: имя, домен, группу и источник кампании и страну в фильтре гео-потока |
| DELETE | `/api/campaigns/{id}` | убрать кампанию из базы сервиса (в Keitaro не меняется) |
| GET | `/api/campaigns/{id}/stats?days=7` | статистика из `POST /report/build`: итоги, клики по дням, по потокам и офферам |
| POST | `/api/campaigns/{id}/fetch` | Fetch streams from KT |
| POST | `/api/streams/{id}/offers` | добавить оффер `{offer_id}` |
| POST | `/api/streams/{id}/offers/{offer_id}/remove` | Remove |
| POST | `/api/streams/{id}/offers/{offer_id}/bring-back` | Bring back |
| POST | `/api/streams/{id}/offers/{offer_id}/pin` | `{pinned, share?}` |
| POST | `/api/streams/{id}/cancel` | Cancel |
| POST | `/api/streams/{id}/push?force=false` | Push to KT; `409`, если поток изменён в Keitaro после загрузки, `force=true` перезаписывает |

Ошибки приложения возвращаются как 400 или 404, ошибки Keitaro как 502, всегда с полем `detail`.

## Структура

```
app/
  main.py             сборка приложения: lifespan, проверка входа, обработчики ошибок
  cli.py              python -m app.cli: создание пользователей и смена пароля
  core/               то, что не зависит от предметной области
    config.py         настройки из .env
    db.py             движок и сессии SQLAlchemy
    errors.py         AppError, NotFound, Conflict → 400 / 404 / 409
    security.py       хеш паролей (scrypt), подписанный токен сессии, текущий пользователь
    cache.py          простой TTL-кэш списков
  keitaro/client.py   async-клиент Keitaro Admin API (httpx)
  models/             таблицы: campaign, stream (Stream, StreamOffer), user, change_log
  schemas/            pydantic-схемы запросов и ответов API
  services/           бизнес-логика, не знает про HTTP
    weights.py        пересчёт долей с пинами
    streams.py        fetch / add / remove / bring back / pin / cancel / push, проверка конфликтов
    campaigns.py      создаватор, изменение кампании и её настроек, включение и выключение
    stats.py          отчёты Keitaro: кампания, потоки, офферы
    offers.py         каталог офферов и где они используются
    references.py     домены, группы, источники; создание групп
    audit.py          журнал изменений
    users.py          пользователи: вход, создание, смена пароля
  api/                JSON API, по роутеру на раздел: campaigns, streams, offers, references; deps.py
  web/                всё, что относится к HTML-интерфейсу
    pages.py          страницы
    auth.py           вход и выход
    templating.py     Jinja2 и пути к шаблонам и статике
    templates/        Jinja2-шаблоны
    static/           app.js (jQuery) и app.css
migrations/           Alembic
tests/                unittest; фейковый Keitaro и SQLite в памяти
```

Зависимости идут в одну сторону: `api` и `web` → `services` → `models`, `keitaro`, `core`. Сервисы не импортируют ничего из FastAPI, поэтому их тестируют напрямую, без HTTP.

## Замечания

- Keitaro стоит за Cloudflare, который блокирует стандартный User-Agent Python-клиентов (ошибка 1010). Клиент отправляет собственный `User-Agent: etolegko-keitaro-wrapper/0.1`.
- При создании кампании сначала создаётся сама кампания, затем два потока. Если поток не создался, кампания удаляется, и ошибка сообщает об этом.
- Группу кампаний можно создать прямо из формы («+ Новая группа»). Источники трафика API-ключ создавать не может (Keitaro отвечает 403), поэтому их можно только выбирать из списка.
- API-ключу тестового трекера доступен только один оффер, а прав на создание офферов у него нет. Поэтому сценарий с несколькими офферами (например 3 → 4 по 25%) проверен тестами на фейковом Keitaro, а вживую проверен цикл на одном оффере.
