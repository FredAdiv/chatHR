# ChatHR — Local Development Setup

## Prerequisites

- **Docker Desktop** installed and running ([download](https://www.docker.com/products/docker-desktop/))
- Git

## Quick Start

### 1. Clone the repository

```bash
git clone https://github.com/FredAdiv/chatHR.git
cd chatHR
```

### 2. Create your local `.env` file

```bash
cp .env.example .env
```

The `.env.example` contains safe dev placeholders that work out of the box.
Do not commit `.env` — it is gitignored.

### 3. Start all services

```bash
docker compose up --build
```

First build may take a few minutes while Docker pulls images and builds the API/web containers.

### 4. Open the app

| Service | URL |
|---|---|
| Frontend (chat UI) | http://localhost:3000 |
| API (FastAPI) | http://localhost:8000 |
| API health check | http://localhost:8000/health |
| MinIO console | http://localhost:9001 (user: `minioadmin`, password: `minioadmin`) |
| PostgreSQL | `localhost:5432` |
| Redis | `localhost:6379` |

### 5. Verify the API is healthy

```bash
curl http://localhost:8000/health
```

Expected response: `{"status": "ok", ...}`

## Notes

- **No real secrets in `.env.example`** — all values are safe dev placeholders.
- The `OPENROUTER_API_KEY` is not needed unless you switch `LLM_PROVIDER=openrouter`.
- The symlink warning (`project loaded from symlink without explicit name`) is harmless.
- The app runs with `LLM_PROVIDER=fake-local` and `EMBEDDING_PROVIDER=fake-local` by default — no external AI calls in dev.

## טעינת נתוני demo לצ'אט

לבדיקה מלאה של ה-RAG flow (שאלה → retrieval → תשובה עם כרטיסי מקור), הרץ לאחר `docker compose up --build`:

```bash
docker compose exec api alembic upgrade head
docker compose exec api python -m scripts.seed_roles
docker compose exec api python -m scripts.create_initial_admin
docker compose exec api python -m scripts.seed_demo_chat_data
```

לאחר מכן:
- **כניסה:** `chat@example.com` / `chat_dev_password`
- **הקשר:** משרדי ממשלה
- **שאלת בדיקה:** `מה הכללים לגבי חופשת מחלה?`
- **צפוי:** תשובת LLM (fake-local placeholder) + כרטיסי מקור מ-"Demo HR Policy Source"

> **שים לב:** נתוני הdemo אינם מקור רשמי אמיתי — לצורכי בדיקה בלבד.

## טעינת מקור רשמי יחיד לצ'אט

לטעינת דף gov.il אמיתי לתוך אינדקס חדש ופעיל (מחליף כל אינדקס קודם):

```bash
docker compose exec api python -m scripts.load_single_source_to_active_index \
  "https://www.gov.il/he/departments/policies/2017_des87"
```

**ארגומנטים אופציונליים:**

| דגל | ברירת מחדל | תיאור |
|-----|-----------|-------|
| `--context-type` | `government_ministries` | `government_ministries` / `defense_system` / `health_system` |
| `--authority-level` | `3` | 1-5, נמוך = עוצמה גבוהה יותר |
| `--source-name` | נגזר מ-URL | שם קריא לאדם |
| `--index-version` | `manual-local-v1` | תווית גרסת האינדקס |

**אחרי הרצה מוצלחת:**
- **כניסה:** `chat@example.com` / `chat_dev_password`
- **הקשר:** המתאים ל-`--context-type` שבחרת
- **שאל שאלה** הקשורה למסמך שנטען
- **צפוי:** תשובת LLM (fake-local placeholder) + כרטיסי מקור מהמקור שנטען

> **הגבלות אבטחה:** רק URLים של gov.il מתקבלים. הסקריפט מגן מפני SSRF.
> תוכן הדף נשמר ב-MinIO בלבד — לא ב-DB וגם לא בלוגים.

## Stopping services

```bash
docker compose down
```

To also remove volumes (wipes DB and MinIO data):

```bash
docker compose down -v
```
