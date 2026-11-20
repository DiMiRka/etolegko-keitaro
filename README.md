# Keitaro wrapper

Обёртка над [Keitaro](https://keitaro.io) Admin API: создание кампаний по шаблону и редактор офферов в потоках с отложенной публикацией.

- **Создаватор кампаний.** Имя, гео и оффер превращаются в кампанию с двумя потоками: поток 1 отправляет трафик из указанной страны на `https://google.com`, поток 2 отправляет всех остальных на выбранный оффер. Домен, группа и источник выбираются из списков Keitaro (по умолчанию значения из настроек). Ротация «по позиции» и CPC 0 USD ставятся всегда.
- **Редактор потоков.** Fetch забирает потоки из Keitaro. Офферы можно добавлять, удалять (removed, с кнопкой Bring back) и закреплять их долю. Веса пересчитываются сразу, поток подсвечивается жёлтым, пока изменения не опубликованы. Push to KT публикует поток, Cancel откатывает несохранённые изменения.

Стек: FastAPI, SQLAlchemy 2.0 (async), Alembic, httpx, pydantic-settings, Jinja2 + jQuery + Select2. Тесты на `unittest`.

## Запуск в Docker

Нужен Docker с Compose v2.

```powershell
copy .env.example .env            # Linux/macOS: cp .env.example .env
```

Впишите в `.env` значение `KEITARO_API_KEY` (в админке Keitaro: Профиль → API ключи), затем:

```powershell
docker compose up -d --build
```

Поднимутся PostgreSQL и приложение. При старте контейнер приложения сам применяет миграции (`alembic upgrade head`). Интерфейс откроется на http://localhost:8000, документация API на http://localhost:8000/docs. `DATABASE_URL` из `.env` внутри Docker не используется: приложение подключается к сервису `db`.

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

Примените миграции и запустите приложение:

```powershell
alembic upgrade head
uvicorn app.main:app --reload
```

Приложение откроется на http://localhost:8000, документация API на http://localhost:8000/docs.

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
python -m unittest discover -s tests
```

Тестам не нужны ни сеть, ни `.env`. Keitaro подменяется фейковым клиентом или `httpx.MockTransport`, база берётся SQLite в памяти.

## Настройки

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `KEITARO_URL` | `https://tlgk.host` | адрес трекера, путь `/admin_api/v1` клиент добавляет сам |
| `KEITARO_API_KEY` | — | ключ Admin API |
| `DATABASE_URL` | `sqlite+aiosqlite:///./app.db` | база приложения |
| `KEITARO_TIMEZONE` | `Europe/Moscow` | часовой пояс отчётов: границы дней и «сегодня» |
| `CAMPAIGN_PREFIX` | `test_mironov_` | префикс имени новой кампании |
| `KEITARO_DOMAIN_ID` | `1813` | домен, выбранный в форме создания по умолчанию |
| `KEITARO_GROUP_ID` | `10332` | группа по умолчанию (FORTESTS) |
| `KEITARO_TRAFFIC_SOURCE_ID` | `836` | источник по умолчанию (FORTESTS) |

## Как это работает

### Состояние оффера в потоке

У каждого оффера в потоке хранятся рабочие поля (`share`, `state`: `active` или `removed`) и снимок последней публикации (`published_share`, `published_state`). Поток жёлтый, если хотя бы у одного оффера рабочие поля отличаются от снимка. Отдельного флага «грязный» нет, он вычисляется.

| Действие | Что происходит |
|---|---|
| **Fetch** | Потоки обновляются по `stream_id`, удалённые в Keitaro потоки удаляются у нас. Доли берутся из Keitaro как есть. Оффер, которого больше нет в Keitaro, становится `removed` с долей 0 и кнопкой Bring back. Неопубликованные изменения сбрасываются к состоянию Keitaro, пины сохраняются. Поток без офферов (например редирект с фильтром) сохраняется просто как поток, его содержимое не разбирается. |
| **Add** | Оффер добавляется без снимка, веса пересчитываются. Если оффер уже лежит в архиве, он возвращается (Bring back). |
| **Remove** | Опубликованный оффер становится `removed` с долей 0 и остаётся в архиве. Ещё не опубликованный оффер просто удаляется. |
| **Bring back** | Оффер снова `active`, веса пересчитываются. |
| **Pin** | Доля закрепляется: текущая или заданная вручную. |
| **Cancel** | Офферы без снимка удаляются, остальным возвращаются доля и статус из снимка. |
| **Push** | В `PUT /streams/{id}` уходит список активных офферов с долями (Keitaro заменяет список целиком). После успеха снимок приравнивается к рабочим полям. При ошибке поток остаётся жёлтым, текст ошибки сохраняется. |

### Пересчёт весов

- Закреплённые офферы сохраняют долю.
- Остаток `100 − сумма закреплённых` делится поровну между активными незакреплёнными. Проценты целые, лишние единицы достаются первым по порядку (34 / 33 / 33).
- Удалённые офферы получают 0.
- Сумма активных всегда ровно 100. Если это невозможно (закреплённые в сумме больше 100, или закреплены все активные, но в сумме не 100), операция отклоняется с понятной ошибкой и ничего не меняет.

Keitaro сам сумму долей не проверяет (принимает и 99), поэтому проверка выполняется на нашей стороне перед Push.

### Статистика

В карточке кампании показана статистика за последние 7 дней, включая сегодня, в часовом поясе `KEITARO_TIMEZONE`: клики, уникальные клики, конверсии, CR, доход и график кликов по дням. У каждого потока указаны клики за сегодня и за период, у каждого оффера клики и тренд по дням. Всё это собирается одним запросом `POST /report/build` с разбивкой по `stream_id`, `offer_id` и `day` и фильтром по кампании. Дни без кликов показываются нулями.

## API

| Метод | Путь | Описание |
|---|---|---|
| GET | `/api/offers?q=` | поиск офферов Keitaro по имени или ID (кэш 60 с) |
| GET | `/api/campaigns` | кампании в нашей базе |
| GET | `/api/references` | домены, группы кампаний и источники из Keitaro (кэш 5 мин) и значения по умолчанию |
| POST | `/api/campaigns` | создать кампанию `{name, geo, offer_id, domain_id?, group_id?, traffic_source_id?}` |
| POST | `/api/campaigns/import` | подключить существующую кампанию `{keitaro_id}` |
| GET | `/api/campaigns/{id}` | кампания с потоками и офферами |
| PATCH | `/api/campaigns/{id}` | изменить `{name?, geo?, domain_id?, group_id?, traffic_source_id?}` сразу в Keitaro: имя, домен, группу и источник кампании и страну в фильтре гео-потока |
| DELETE | `/api/campaigns/{id}` | убрать кампанию из нашей базы (в Keitaro не меняется) |
| GET | `/api/campaigns/{id}/stats?days=7` | статистика из `POST /report/build`: итоги, клики по дням, по потокам и офферам |
| POST | `/api/campaigns/{id}/fetch` | Fetch streams from KT |
| POST | `/api/streams/{id}/offers` | добавить оффер `{offer_id}` |
| POST | `/api/streams/{id}/offers/{offer_id}/remove` | Remove |
| POST | `/api/streams/{id}/offers/{offer_id}/bring-back` | Bring back |
| POST | `/api/streams/{id}/offers/{offer_id}/pin` | `{pinned, share?}` |
| POST | `/api/streams/{id}/cancel` | Cancel |
| POST | `/api/streams/{id}/push` | Push to KT |

Ошибки приложения возвращаются как 400 или 404, ошибки Keitaro как 502, всегда с полем `detail`.

## Структура

```
app/
  main.py        приложение, обработчики ошибок
  config.py      настройки из .env
  db.py, models.py
  keitaro.py     async-клиент Keitaro Admin API
  weights.py     пересчёт долей
  streams.py     fetch / add / remove / bring back / pin / cancel / push
  campaigns.py   создаватор кампаний
  offers.py      кэш и поиск офферов
  api.py, web.py JSON API и страницы
  templates/, static/
migrations/      Alembic
tests/
```

## Замечания

- Keitaro стоит за Cloudflare, который блокирует стандартный User-Agent Python-клиентов (ошибка 1010). Клиент отправляет собственный `User-Agent: etolegko-keitaro-wrapper/0.1`.
- При создании кампании сначала создаётся сама кампания, затем два потока. Если поток не создался, кампания удаляется, и ошибка сообщает об этом.
- API-ключу тестового трекера доступен только один оффер, а прав на создание офферов у него нет. Поэтому сценарий с несколькими офферами (например 3 → 4 по 25%) проверен тестами на фейковом Keitaro, а вживую проверен цикл на одном оффере.
