# Bharathi local development (Windows PostgreSQL, no Docker)

## Detected setup (this machine)

| Item | Status |
|------|--------|
| PostgreSQL port | **5432** (`LISTENING` on `127.0.0.1`) |
| Database `bharathi_erp` | **Exists** — owner **`bharathi_user`** |
| Role `bharathi_user` | **Present**, `LOGIN` enabled — password must match `DATABASE_URL` in `backend/.env` |
| Shell `DATABASE_URL` | Some terminals set `insights_user` — `app/core/config.py` loads `backend/.env` with **override** so Bharathi URL wins |

Quick check (no passwords printed):

```powershell
cd backend
python scripts/verify_bharathi_db_connection.py
```

`backend/.env` targets:

`postgresql+psycopg://bharathi_user:bharathi_dev@127.0.0.1:5432/bharathi_erp`

Do not use port `55432` unless you run Docker Compose for Bharathi Postgres (you asked for **no Docker**).

---

## Step 1 — Fix DB role (needs Postgres superuser; your approval)

In **pgAdmin** or psql as `postgres` (or another superuser), run once:

```sql
-- Only if role is missing (setup script can do this too)
-- CREATE ROLE bharathi_user WITH LOGIN PASSWORD 'choose-a-strong-local-password';

ALTER ROLE bharathi_user WITH LOGIN PASSWORD 'choose-a-strong-local-password';
ALTER DATABASE bharathi_erp OWNER TO bharathi_user;
GRANT ALL ON SCHEMA public TO bharathi_user;
ALTER SCHEMA public OWNER TO bharathi_user;
```

**Or** from `backend/` (PowerShell):

```powershell
$env:POSTGRES_ADMIN_PASSWORD = "<your-postgres-superuser-password>"
$env:POSTGRES_ADMIN_PORT = "5432"
$env:APP_DB_PASSWORD = "<same-password-you-want-in-.env>"
python scripts/setup_bharathi_postgres_local.py
```

Then set `DATABASE_URL` in `backend/.env` to match `APP_DB_PASSWORD` (never commit `.env`).

---

## Step 2 — Confirm connection

```powershell
cd backend
python -c "from app.core.config import get_settings; from sqlalchemy import create_engine, text; e=create_engine(get_settings().database_url); c=e.connect(); print(c.execute(text('SELECT current_database(), current_user, inet_server_port()')).fetchone())"
```

Expect: `('bharathi_erp', 'bharathi_user', 5432)`.

---

## Step 3 — Alembic

```powershell
cd backend
alembic upgrade head
alembic current
```

---

## Step 4 — Start API (seeds tenant, roles, dev startup data)

```powershell
cd backend
.\venv\Scripts\activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

- Health: http://127.0.0.1:8000/health  
- Docs: http://127.0.0.1:8000/docs  

Startup (non-production) runs `seed_roles` including **Admin**, **Accountant**, **Supervisor** (`app/core/rbac_constants.py`).

---

## Step 5 — First Admin account (no shared demo password)

`ALLOW_PUBLIC_REGISTRATION=false` in `.env` blocks the register UI.

**Recommended (one-time, local only):**

1. In `backend/.env`, temporarily set `ALLOW_PUBLIC_REGISTRATION=true`.
2. Restart uvicorn.
3. Open http://localhost:5173/register — create **your** company + Admin with **your** password (12+ chars).
4. Set `ALLOW_PUBLIC_REGISTRATION=false` again and restart.

**Avoid** relying on `seed_admin_user` default (`admin@gnssoftwares.com` / `Admin123!`) in shared environments; change the password immediately if that seed ran.

---

## Step 6 — Frontend

```powershell
cd frontend
npm install
copy .env.example .env
npm run dev
```

Login: http://localhost:5173/login — role **Admin**, your email/password.

---

## Local demo login (Admin / Accountant / Supervisor / Store Manager)

For Bharathi ERP UI review only. Fails closed in production or when disabled.

1. In `backend/.env` (gitignored):

   - `ENVIRONMENT=development`
   - `ENABLE_LOCAL_DEMO_LOGIN=true`
   - `LOCAL_DEMO_PASSWORD=<your 12+ char secret>`
   - `LOCAL_DEMO_UI_EMAIL=demo@bharathi.local` (optional)
   - `FRONTEND_BASE_URL=http://localhost:5173`

2. Create demo users in PostgreSQL `bharathi_erp` / `bharathi_user`, or in the
   explicitly enabled local SQLite database `backend/bharathi_local_dev.db`.

   **Re-run after every `LOCAL_DEMO_PASSWORD` change:**

```powershell
cd backend
Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue
python scripts/setup_local_demo_users.py
```

3. Restart uvicorn. On http://localhost:5173/login:

   - Email: `demo@bharathi.local` (placeholder appears when demo is active)
   - Password: value from `LOCAL_DEMO_PASSWORD` (never committed)
   - Role: **Admin**, **Accountant**, **Supervisor**, or **Store Manager**

Each role maps to a **separate** demo user with real RBAC (not role impersonation).

**Before deployment:** `ENABLE_LOCAL_DEMO_LOGIN=false`, remove `LOCAL_DEMO_PASSWORD`, run `python scripts/remove_local_demo_users.py`.

---

## Troubleshooting

| Symptom | Cause |
|---------|--------|
| Uvicorn: `DATABASE_URL is required` | Missing `backend/.env` |
| `password authentication failed for user "bharathi_user"` | Password in `DATABASE_URL` / `DATABASE_PASSWORD` must match pgAdmin for **bharathi_user** (test with Query Tool as that user, not postgres superuser). Run Step 1 if role/owner wrong |
| Alembic: `permission denied for schema public` | DB owner must be `bharathi_user` (Step 1) |
| Alembic uses `SQLiteImpl` | Wrong `DATABASE_URL` in `.env` or unset; use PostgreSQL URL |
| verify script fails but psql works | `@` or `#` in password breaks URL parsing — use `%40` in `DATABASE_URL` or set `DATABASE_PASSWORD` |
| `alembic upgrade` DuplicateTable on Bharathi | Dev `create_all` created tables first — `alembic stamp head` after schema exists (see migration idempotent guard) |
| Login 503 / DB error in health | Migrations not applied or wrong port |
| API uses `insights_user` | Stale shell `DATABASE_URL`; restart terminal or rely on `.env` override |