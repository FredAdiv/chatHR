# ChatHR — Frontend MVP

## Overview

A minimal Next.js 14 frontend (App Router) that connects to the ChatHR FastAPI backend.
Hebrew UI, RTL layout, no design system.

## Pages

| Route | Description |
|---|---|
| `/` | Redirects to `/chat` (if logged in) or `/login` |
| `/login` | Login form (email + password) |
| `/chat` | Main chat interface |

## Features

- Login via email/password → JWT stored in `localStorage`
- Context selector: משרדי ממשלה / מערכת הביטחון / מערכת הבריאות
- New conversation button
- Chat message history (user + assistant bubbles)
- Source cards under each assistant answer
- Feedback: 👍 / 👎 + optional comment
- Safe error messages for: auth failure, privacy block (422), no index (503), network error

## Auth Storage — MVP Note

JWT is stored in `localStorage` for MVP convenience.
**Production must use `httpOnly` cookies or a proper session mechanism.**

## Environment Variables

Copy `apps/web/.env.example` to `apps/web/.env.local`:

```
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
```

## Running Locally

```bash
# From apps/web:
npm install
npm run dev
# Open http://localhost:3000
```

## With Docker Compose

```bash
docker compose up --build
# API at :8000, Web at :3000
```

## Manual Smoke Test

1. `docker compose up --build`
2. Create initial admin user via `/dev/seed` or migration (if not seeded)
3. Open `http://localhost:3000`
4. Login with a user that has `chat_user` or `system_admin` role
5. Select context type, click **שיחה חדשה**
6. Send a message
7. Verify assistant response appears
8. Verify sources shown (or "no sources" fallback message from backend)
9. Click 👍 or 👎, add optional comment, click **שלח**
10. Verify "תודה על המשוב!" confirmation

## API Endpoints Used

| Method | Path | Purpose |
|---|---|---|
| POST | `/auth/login` | Login (form-encoded `username`+`password`) |
| GET | `/auth/me` | Get current user |
| POST | `/chat/conversations` | Create conversation |
| POST | `/chat/conversations/{id}/messages` | Send message |
| POST | `/chat/messages/{id}/feedback` | Submit feedback |

## Known MVP Limitations

- No conversation history list (only active conversation shown)
- JWT in localStorage (not production-safe)
- No streaming (full response only)
- No real OpenRouter (fake-local LLM by default)
- No admin UI
- No production SSO
- No frontend unit tests (manual smoke test provided)
- No real semantic embeddings
- Source cards link to `source_url` if available; no in-app document viewer
