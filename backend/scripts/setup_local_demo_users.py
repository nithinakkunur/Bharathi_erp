#!/usr/bin/env python3
"""Create or update Bharathi local demo users (Admin, Accountant, Supervisor, Store Manager).

Requires:
  ENVIRONMENT=development
  ENABLE_LOCAL_DEMO_LOGIN=true
  LOCAL_DEMO_PASSWORD in environment or backend/.env
  PostgreSQL: bharathi_erp @ bharathi_user, or the explicitly enabled local
  SQLite database backend/bharathi_local_dev.db

Does not modify non-demo users or other databases. SQLite use is restricted to
the local development database and requires ALLOW_SQLITE_RUNTIME=1.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.local_demo_login import (
    LOCAL_DEMO_ACCOUNT_EMAIL_BY_ROLE,
    is_local_demo_login_active,
)
from app.core.seed_roles import seed_roles
from app.core.seed_tenant import seed_tenant
from app.models.role import Role
from app.models.user import User
from app.services.auth_service import hash_password


def _verify_database(engine) -> None:
    if engine.dialect.name == "sqlite":
        settings = get_settings()
        if (
            settings.environment.strip().lower() != "development"
            or not settings.allow_sqlite_runtime
        ):
            raise SystemExit(
                "Refusing SQLite demo-user setup unless ENVIRONMENT=development "
                "and ALLOW_SQLITE_RUNTIME=1."
            )

        database = engine.url.database
        if not database or database == ":memory:":
            raise SystemExit(
                "Refusing SQLite demo-user setup without the local development database file."
            )
        database_path = Path(database)
        if not database_path.is_absolute():
            database_path = (Path.cwd() / database_path).resolve()
        allowed_path = (BACKEND_ROOT / "bharathi_local_dev.db").resolve()
        if database_path != allowed_path:
            raise SystemExit(
                "Refusing SQLite demo-user setup outside backend/bharathi_local_dev.db."
            )

        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        print("OK local SQLite development database")
        return

    if engine.dialect.name != "postgresql":
        raise SystemExit("Refusing demo-user setup for an unsupported database.")

    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT current_database(), current_user, inet_server_port()")
        ).fetchone()
        db, user, port = row
        if settings_is_postgres_bharathi(engine):
            allowed_dbs = {"bharathi_erp"}
            demo_db = (os.getenv("BHARATHI_DEMO_DATABASE") or "").strip()
            if demo_db:
                allowed_dbs.add(demo_db)
            if user != "bharathi_user" or db not in allowed_dbs:
                raise SystemExit(
                    f"Refusing to run: connected as {db!r} / {user!r} "
                    f"(expected bharathi_user on one of {sorted(allowed_dbs)})."
                )
        print(f"OK database {db} @ {user} port {port}")


def settings_is_postgres_bharathi(engine) -> bool:
    return engine.dialect.name == "postgresql"


def _assign_single_role(db: Session, user: User, role_name: str, tenant_id: int) -> None:
    role = db.scalars(
        select(Role).where(Role.tenant_id == tenant_id, Role.name == role_name)
    ).first()
    if not role:
        raise SystemExit(f"Missing role {role_name!r} — run app startup or seed_roles first.")
    user.roles = [role]


def main() -> int:
    get_settings.cache_clear()
    settings = get_settings()
    if not is_local_demo_login_active(settings):
        print(
            "Local demo login is not active. Set ENVIRONMENT=development, "
            "ENABLE_LOCAL_DEMO_LOGIN=true, LOCAL_DEMO_PASSWORD, and FRONTEND_BASE_URL=http://localhost:5173"
        )
        return 1

    password = (settings.local_demo_password or "").strip()
    if len(password) < 12:
        print("LOCAL_DEMO_PASSWORD must be at least 12 characters.")
        return 1

    from sqlalchemy.engine.url import make_url

    url = make_url(settings.database_url)
    demo_db = (os.getenv("BHARATHI_DEMO_DATABASE") or "").strip()
    if demo_db:
        url = url.set(database=demo_db)
    engine = create_engine(url)
    _verify_database(engine)

    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        seed_tenant(db)
        seed_roles(db, tenant_id=1)
        hashed = hash_password(password)

        for role_name, email in LOCAL_DEMO_ACCOUNT_EMAIL_BY_ROLE.items():
            user = db.scalars(
                select(User).where(User.email == email.lower())
            ).first()
            display = f"Bharathi Demo ({role_name})"
            if user is None:
                user = User(
                    tenant_id=1,
                    email=email.lower(),
                    hashed_password=hashed,
                    full_name=display,
                    is_active=True,
                    email_verified=True,
                )
                db.add(user)
                db.flush()
            else:
                user.hashed_password = hashed
                user.full_name = display
                user.is_active = True
                user.email_verified = True
            _assign_single_role(db, user, role_name, tenant_id=1)
            print(f"Upserted demo user {email} -> role {role_name}")

        db.commit()
        print(
            f"Demo UI email: {settings.local_demo_ui_email} "
            f"(use with role selector; password from LOCAL_DEMO_PASSWORD only)"
        )
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())