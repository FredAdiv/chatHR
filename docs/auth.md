# Authentication & Authorization — Local MVP

## Overview

ChatHR uses stateless JWT bearer tokens. All tokens are issued by the FastAPI backend and verified on every request; no session state is stored on the server.

## Endpoints

| Method | Path | Auth required | Role required |
|--------|------|---------------|---------------|
| `POST` | `/auth/login` | No | — |
| `GET` | `/auth/me` | Yes | any active user |
| `GET` | `/admin/users` | Yes | user_admin or system_admin |
| `POST` | `/admin/users` | Yes | user_admin or system_admin |
| `PATCH` | `/admin/users/{id}/roles` | Yes | user_admin or system_admin |
| `PATCH` | `/admin/users/{id}/deactivate` | Yes | user_admin or system_admin |
| `GET` | `/dev/db-info` | Yes | system_admin |

## Token Flow

1. `POST /auth/login` with `application/x-www-form-urlencoded` body: `username=<email>&password=<password>`
2. Returns `{"access_token": "...", "token_type": "bearer"}`
3. All subsequent requests: `Authorization: Bearer <token>`

Tokens expire after `ACCESS_TOKEN_EXPIRE_MINUTES` (default: 60). There is no refresh token in the MVP.

## Password Storage

Passwords are hashed with `bcrypt` (cost factor 12 by default). The `password_hash` field is never returned in any API response.

## RBAC Roles

All role checks are server-side only. Client-side role information (from `/auth/me`) is for display only and must never gate access.

| Role | Permissions |
|------|-------------|
| `chat_user` | Start and continue chat sessions |
| `faq_manager` | Create and edit FAQ entries |
| `user_admin` | Create users, assign/remove roles, deactivate users |
| `feedback_reviewer` | View and label user feedback |
| `knowledge_admin` | Manage the knowledge base |
| `system_admin` | All of the above plus system-level access |

## Bootstrap Initial Admin

After running migrations for the first time:

```bash
INITIAL_ADMIN_EMAIL=admin@your-org.gov.il \
INITIAL_ADMIN_PASSWORD=<strong-password> \
python -m scripts.create_initial_admin
```

This is idempotent — safe to run multiple times. Requires the `system_admin` role row to exist (seeded by `seed_roles.py`).

## Security Constraints

- No secrets in source code — all loaded from `.env`
- `password_hash` never appears in API responses
- Passwords and tokens are never logged
- No anonymous access to any protected endpoint
- No client-side-only authorization — all checks enforced in `deps.py`
- No SSO in this MVP; `password_hash` is nullable to allow future SSO users
