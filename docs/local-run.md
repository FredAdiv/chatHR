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
> הסקריפט מאנדקס רק את ה-URL שסיפקת בפועל — אינו מחפש באינטרנט ואינו סורק קישורים נוספים.

**אם מתקבלת שגיאת HTTP 403:**
חלק מדפי gov.il חוסמים הורדה אוטומטית (עמודי אוסף/חיפוש/דינמיים).
- נסה **קישור ישיר ל-PDF או מסמך רשמי** מתוך gov.il (לדוגמה: קישור ישיר לקובץ PDF של חוזר מנכ"ל).
- הימנע מדפי ניווט ראשיים או דפי חיפוש.

## טעינת קובץ מקומי — התקשי״ר

לטעינת מסמך רשמי שהורדת ידנית (למשל התקשי״ר) לתוך אינדקס חדש ופעיל:

### 1. הכן את תיקיית local-data

```bash
mkdir -p local-data
```

העתק את הקובץ שהורדת:
```bash
cp /path/to/takshir.pdf local-data/takshir.pdf
```

> **חשוב:** אל תעלה קבצים אמיתיים ל-Git — `local-data/` מוחרגת ב-`.gitignore`.

### 2. הפעל את השירותים

```bash
docker compose up --build -d
docker compose exec api alembic upgrade head
docker compose exec api python -m scripts.seed_roles
docker compose exec api python -m scripts.create_initial_admin
docker compose exec api python -m scripts.seed_demo_chat_data
```

### 3. טען את הקובץ לאינדקס

```bash
docker compose exec api python -m scripts.load_local_file_to_active_index \
  "/app/local-data/takshir.pdf" \
  --source-name "תקשי״ר - מסמך בדיקה מקומי" \
  --source-url "https://www.gov.il/he/departments/policies/takshir" \
  --context-type government_ministries \
  --authority-level 1 \
  --index-version "takshir-local-v1"
```

**ארגומנטים:**

| דגל | חובה | תיאור |
|-----|------|-------|
| `file_path` | ✓ | נתיב הקובץ בתוך ה-container |
| `--source-name` | ✓ | שם קריא לאדם |
| `--source-url` | ✓ | URL לציטוט בלבד (לא מורד) |
| `--context-type` | | `government_ministries` / `defense_system` / `health_system` [ברירת מחדל: `government_ministries`] |
| `--authority-level` | | 1-5, נמוך = עוצמה גבוהה יותר [ברירת מחדל: 1] |
| `--index-version` | | תווית גרסת האינדקס [ברירת מחדל: `local-file-v1`] |

**סיומות נתמכות:** `.pdf`, `.docx`, `.doc`, `.xlsx`, `.xls`, `.html`, `.htm`, `.txt`

### 4. בדיקה ידנית

- **כניסה:** `chat@example.com` / `chat_dev_password`
- **הקשר:** משרדי ממשלה
- **שאל שאלה** הקשורה למסמך שנטען
- **צפוי:** תשובת LLM (fake-local placeholder) + כרטיסי מקור עם `authority_level=1`

> **הגבלות:**
> - הסקריפט מאנדקס רק את הקובץ המקומי שסיפקת — אינו מחפש באינטרנט ואינו מוריד מ-gov.il.
> - ה-`source_url` משמש לציטוט בלבד (metadata).
> - הקובץ המקומי חייב להיות מסמך רשמי שהשגת בעצמך.
> - תוכן הגלם נשמר ב-MinIO בלבד — לא ב-DB, לא בלוגים, ולא בפלט.

## העלאת מסמך ידנית דרך ממשק הניהול

מסך הניהול מאפשר למשתמשים עם הרשאת `knowledge_admin` או `system_admin` להעלות מסמכים ישירות לבסיס הידע דרך הדפדפן.

### פתיחת המסך

לאחר `docker compose up --build`, היכנס לצ'אט עם משתמש `knowledge_admin` או `system_admin`. כפתור **"טעינת מסמך ידע"** יופיע בפס הכותרת. לחיצה עליו תנווט למסך ההעלאה.

ניתן לנווט גם ישירות:

```
http://localhost:3000/admin/knowledge/upload
```

> **הרשאה:** רק משתמשים עם תפקיד `knowledge_admin` או `system_admin` יכולים לגשת למסך. משתמש chat_user רגיל יקבל שגיאת הרשאה.
> **שים לב:** כדי שהמסך יהיה נגיש, יש להריץ `docker compose up --build` לאחר כל עדכון קוד — המסך לא ייכלל בבנייה ישנה של ה-container.

### שדות הטופס

| שדה | חובה | תיאור |
|-----|------|-------|
| קובץ | ✓ | המסמך להעלאה |
| כותרת | ✓ | שם קריא למסמך |
| סוג מסמך | ✓ | סוג סמנטי, למשל: `takshir`, `policy`, `circular` |
| רמת סמכות | ✓ | 1-5, נמוך = עוצמה גבוהה יותר |
| קישור מקור | | URL לציטוט בלבד (אינו מורד) |
| הקשר מערכת | | הקשר ארגוני (אופציונלי) |
| הערות | | הערות אדמין פנימיות (אופציונלי) |

**סיומות נתמכות:** `.pdf`, `.docx`, `.doc`, `.xlsx`, `.xls`, `.html`, `.htm`, `.txt` · עד 20 MB

### טעינת תקשי״ר — פריסט מהיר

לחץ על הכפתור **"טען פריסט — תקשי״ר"** בראש הטופס. הפריסט ממלא אוטומטית:
- **כותרת:** תקשי״ר
- **סוג מסמך:** takshir
- **רמת סמכות:** 1

בחר את קובץ ה-PDF של התקשי״ר ולחץ **"העלה מסמך"**.

### מצבי חזרה (status)

| מצב | משמעות |
|-----|--------|
| `pending_processing` | הקובץ הועלה בהצלחה ל-MinIO והמטא-דאטה נשמר בבסיס הנתונים — מחכה לעיבוד (parsing + indexing) |

> **אחרי ההעלאה:** הפעל את סקריפט האינדוקס הידני להשלמת תהליך הפרסינג, ה-chunking וה-embedding:
> ```bash
> docker compose exec api python -m scripts.load_local_file_to_active_index \
>   "/app/local-data/<filename>" \
>   --source-name "<title>" \
>   --source-url "https://www.gov.il/..."
> ```

### אזהרת פרטיות

אל תעלה מסמכים המכילים **פרטים מזהים אישיים** של עובדים (שם, מספר ת.ז., פרטי קשר, נתוני שכר וכד׳). המסמך נשמר ב-MinIO ועשוי לשמש כבסיס לתשובות בצ׳אט.

- תוכן הגלם **אינו** נשמר ב-DB, בלוגים, או בתגובות ה-API.
- כל העלאה מתועדת ב-Audit Log (שם קובץ, סוג, רמת סמכות, מצב).

## מחזור חיי אינדקס ידע

אינדקס גרסה (`IndexVersion`) עובר את מחזור החיים הבא:

| מצב | משמעות |
|-----|--------|
| `building` | ה-embedding בתהליך |
| `draft` | עיבוד הסתיים — ממתין לבדיקות איכות |
| `quality_check_failed` | בדיקות איכות נכשלו |
| `ready` | בדיקות איכות עברו — מוכן להפעלה |
| `active` | פעיל — משמש את הצ'אט |
| `archived` | גרסה קודמת שהוחלפה |

> **חשוב:** הצ'אט משתמש **רק** בגרסה `active`. כל גרסה אחרת אינה גלויה למשתמשי הצ'אט.

## עיבוד מסמך לאינדקס טיוטה

לאחר העלאה מוצלחת, ניתן לעבד את המסמך לאינדקס טיוטה — ניתוח, פיצול לקטעים, והטמעה — ישירות מממשק הניהול.

### מה קורה בעיבוד

1. המסמך הגולמי נשלף מ-MinIO
2. נמצה טקסט (parsing) לפי סוג הקובץ (`file_format` בפועל)
3. הטקסט מפוצל לקטעים (chunking)
4. נוצרות הטמעות (embeddings) עם ספק fake-local
5. נוצרת גרסת אינדקס חדשה עם `status=draft`

> **חשוב:** האינדקס נשאר במצב `draft` ואינו מופעל אוטומטית.
> המסמך לא יהיה גלוי לשאלות משתמשי צ'אט עד לשלב פרסום נפרד.

### כיצד לעבד

לאחר שהמסמך הועלה בהצלחה, כפתור **"עבד מסמך לאינדקס טיוטה"** יופיע אוטומטית מתחת להודעת ההצלחה. לחיצה עליו תפעיל את העיבוד.

לחלופין, ניתן לקרוא ישירות ל-API:

```
POST /admin/knowledge/documents/{document_id}/process
Authorization: Bearer <token>
```

### מצבי SourceDocument

| מצב | משמעות |
|-----|--------|
| `downloaded` | הקובץ הועלה ל-MinIO, ממתין לעיבוד |
| `processed` | עובד בהצלחה — קיים אינדקס טיוטה |
| `failed` | שגיאת עיבוד — ניתן לנסות שנית |

### API למעקב מצב

```
GET /admin/knowledge/documents/{document_id}
Authorization: Bearer <token>
```

מחזיר metadata בלבד: `document_id`, `title`, `document_type` (סוג סמנטי כגון `takshir`), `file_format` (כגון `pdf`), `authority_level`, `status`, `index_version_id`.
ללא תוכן גלם, ללא hash, ללא מפתחות MinIO.

### מטא-דאטה: סוג סמנטי לעומת פורמט קובץ

| שדה | דוגמה | משמעות |
|-----|--------|---------|
| `document_type` | `takshir` | סוג סמנטי — מה המסמך מבחינה ארגונית |
| `file_format` | `pdf` | פורמט הקובץ — משמש לבחירת ה-parser |

> שדה `document_type` ב-API מחזיר את הסוג הסמנטי שהוזן בטופס ההעלאה.
> שדה `file_format` מחזיר את פורמט הקובץ בפועל.

## בדיקות איכות לאינדקס טיוטה

לאחר עיבוד מוצלח, יש להריץ בדיקות איכות לפני פרסום האינדקס.

### בדיקות מבוצעות (9 בדיקות מקומיות, ללא קריאה ל-LLM)

1. גרסת האינדקס אינה `active`
2. קיים לפחות רשומת embedding אחת
3. כל רשומות ה-embedding מקושרות ל-SourceDocument
4. מטא-דאטה לציטוט שלמה (כותרת + סוג מסמך)
5. רמת סמכות תקינה (1-5)
6. תוכן גלם אינו חשוף ב-API או לוגים
7. מסמכי תקשי״ר: `authority_level=1` מוגדר
8. סניטי לקטעים: אין קטעים ריקים, אין קטעים גדולים מדי
9. מספר קטעים סביר

### כיצד להריץ בדיקות איכות

לאחר עיבוד מוצלח, כפתור **"הרץ בדיקות איכות"** יופיע במסך הניהול. לחיצה עליו תריץ את הבדיקות.

לחלופין, ניתן לקרוא ישירות ל-API:

```
POST /admin/knowledge/index-versions/{index_version_id}/quality-check
Authorization: Bearer <token>
```

**תגובה בהצלחה (כל הבדיקות עברו):**
```json
{
  "index_version_id": "...",
  "overall_passed": true,
  "status": "ready",
  "checks": [...],
  "chunk_count": 42,
  "checked_at": "2026-06-16T..."
}
```

**תגובה בכישלון:**
```json
{
  "overall_passed": false,
  "status": "quality_check_failed",
  "checks": [{ "name": "has_embeddings", "passed": false, "message": "..." }, ...]
}
```

## פרסום אינדקס פעיל

לאחר שבדיקות האיכות עברו (`status=ready`), ניתן לפרסם את האינדקס כגרסה פעילה.

> **אזהרה:** פרסום האינדקס יהפוך אותו למקור הפעיל לתשובות הצ'אט. יש לוודא שהתוכן מאושר.

### כיצד לפרסם

לאחר שבדיקות האיכות עברו, כפתור **"פרסם אינדקס פעיל"** יופיע (ומופעל רק לאחר מעבר בדיקות). לחיצה עליו תפרסם את האינדקס.

לחלופין, ניתן לקרוא ישירות ל-API:

```
POST /admin/knowledge/index-versions/{index_version_id}/activate
Authorization: Bearer <token>
```

**תגובה מוצלחת:**
```json
{
  "index_version_id": "...",
  "status": "active",
  "version_label": "manual-upload-abc12345-20260616",
  "activated_at": "2026-06-16T...",
  "previous_active_id": "...",
  "message": "אינדקס גרסה '...' הופעל בהצלחה."
}
```

### כללי הפעלה

- רק גרסה עם `status=ready` (שעברה בדיקות) ניתנת להפעלה.
- הפעלה מעבירה את הגרסה הפעילה הקיימת למצב `archived` (ניתן לזיהוי לצורך rollback).
- בכל רגע יכולה להיות לכל היותר גרסה אחת `active`.
- כל פרסום מתועד ב-Audit Log.
- תוכן גלם אינו נשמר בתגובה, בלוגים או ב-DB.

### הרשאה נדרשת

`knowledge_admin` או `system_admin`.

## Stopping services

```bash
docker compose down
```

To also remove volumes (wipes DB and MinIO data):

```bash
docker compose down -v
```
