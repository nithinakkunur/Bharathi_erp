"""Local development demo login (Bharathi ERP)."""

import os
import pytest
from sqlalchemy import create_engine, select

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.local_demo_login import (
    LOCAL_DEMO_ACCOUNT_EMAIL_BY_ROLE,
    is_local_demo_login_active,
    try_resolve_local_demo_user,
)
from app.core.seed_roles import seed_roles
from app.core.seed_tenant import seed_tenant
from app.models.role import Role
from app.models.user import User
from app.services.auth_service import hash_password
from scripts.setup_local_demo_users import _verify_database

_DEMO_PASSWORD = "DemoPassw0rd!12"


@pytest.fixture
def demo_login_env(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("ENABLE_LOCAL_DEMO_LOGIN", "true")
    monkeypatch.setenv("LOCAL_DEMO_PASSWORD", _DEMO_PASSWORD)
    monkeypatch.setenv("FRONTEND_BASE_URL", "http://localhost:5173")
    monkeypatch.setenv("LOCAL_DEMO_UI_EMAIL", "demo@bharathi.local")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _seed_demo_users():
    db = SessionLocal()
    try:
        seed_tenant(db)
        seed_roles(db, tenant_id=1)
        hashed = hash_password(_DEMO_PASSWORD)
        for role_name, email in LOCAL_DEMO_ACCOUNT_EMAIL_BY_ROLE.items():
            user = db.scalars(select(User).where(User.email == email)).first()
            if user is None:
                user = User(
                    tenant_id=1,
                    email=email,
                    hashed_password=hashed,
                    full_name=f"Demo {role_name}",
                    is_active=True,
                    email_verified=True,
                )
                db.add(user)
                db.flush()
            else:
                user.hashed_password = hashed
            role = db.scalars(
                select(Role).where(Role.tenant_id == 1, Role.name == role_name)
            ).first()
            user.roles = [role]
        db.commit()
    finally:
        db.close()


def test_demo_login_inactive_by_default(monkeypatch):
    monkeypatch.setenv("ENABLE_LOCAL_DEMO_LOGIN", "false")
    monkeypatch.setenv("LOCAL_DEMO_PASSWORD", "")
    get_settings.cache_clear()
    assert is_local_demo_login_active() is False


def test_demo_login_fails_when_disabled(client, demo_login_env, monkeypatch):
    monkeypatch.setenv("ENABLE_LOCAL_DEMO_LOGIN", "false")
    get_settings.cache_clear()
    _seed_demo_users()
    resp = client.post(
        "/auth/login",
        json={
            "email": "demo@bharathi.local",
            "password": _DEMO_PASSWORD,
            "role": "Admin",
        },
    )
    assert resp.status_code == 401


def test_demo_login_admin_accountant_supervisor_store_manager(client, demo_login_env):
    _seed_demo_users()
    for role in ("Admin", "Accountant", "Supervisor", "Store Manager"):
        resp = client.post(
            "/auth/login",
            json={
                "email": "demo@bharathi.local",
                "password": _DEMO_PASSWORD,
                "role": role,
            },
        )
        assert resp.status_code == 200, (role, resp.text)
        body = resp.json()
        assert body.get("access_token") or body.get("user")
        assert body["user"]["role"] == role


def test_demo_login_wrong_password(client, demo_login_env):
    _seed_demo_users()
    resp = client.post(
        "/auth/login",
        json={
            "email": "demo@bharathi.local",
            "password": "wrong-password-xyz",
            "role": "Admin",
        },
    )
    assert resp.status_code == 401


def test_demo_login_cannot_impersonate_role_via_normal_user(client, register_admin, demo_login_env):
    ctx = register_admin()
    resp = client.post(
        "/auth/login",
        json={
            "email": ctx["email"],
            "password": ctx["password"],
            "role": "Accountant",
        },
    )
    assert resp.status_code == 401


def test_demo_resolve_unit(demo_login_env):
    _seed_demo_users()
    db = SessionLocal()
    try:
        ok = try_resolve_local_demo_user(
            db, "demo@bharathi.local", _DEMO_PASSWORD, "Supervisor"
        )
        assert ok.kind == "ok"
        assert ok.user is not None
        assert ok.user.email == LOCAL_DEMO_ACCOUNT_EMAIL_BY_ROLE["Supervisor"]
    finally:
        db.close()


def test_production_rejects_demo_flag(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("ENABLE_LOCAL_DEMO_LOGIN", "true")
    monkeypatch.setenv("JWT_SECRET_KEY", "x" * 48)
    get_settings.cache_clear()
    with pytest.raises(ValueError, match="ENABLE_LOCAL_DEMO_LOGIN"):
        get_settings()


def test_demo_login_via_api_auth_login_route(client, demo_login_env):
    _seed_demo_users()
    resp = client.post(
        "/api/auth/login",
        json={
            "email": "demo@bharathi.local",
            "password": _DEMO_PASSWORD,
            "role": "Admin",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("success") is True or body.get("data")


def test_local_demo_status_endpoint(client, demo_login_env):
    resp = client.get("/auth/local-demo-login")
    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is True
    assert body["demo_email"] == "demo@bharathi.local"
    assert "Admin" in body["roles"]
    assert "Store Manager" in body["roles"]
    assert "password" not in body


def test_demo_user_setup_allows_only_explicit_local_sqlite_database(tmp_path, monkeypatch):
    import scripts.setup_local_demo_users as demo_setup

    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("ALLOW_SQLITE_RUNTIME", "1")
    monkeypatch.setattr(demo_setup, "BACKEND_ROOT", tmp_path)
    get_settings.cache_clear()

    allowed_path = tmp_path / "bharathi_local_dev.db"
    allowed_engine = create_engine(f"sqlite:///{allowed_path}")
    other_engine = create_engine(f"sqlite:///{tmp_path / 'other.db'}")
    try:
        _verify_database(allowed_engine)
        with pytest.raises(SystemExit, match="outside backend/bharathi_local_dev.db"):
            _verify_database(other_engine)

        monkeypatch.setenv("ALLOW_SQLITE_RUNTIME", "0")
        get_settings.cache_clear()
        with pytest.raises(ValueError, match="ALLOW_SQLITE_RUNTIME=1"):
            _verify_database(allowed_engine)
    finally:
        allowed_engine.dispose()
        other_engine.dispose()
        get_settings.cache_clear()


def test_demo_login_store_manager_resolves_identity(demo_login_env):
    _seed_demo_users()
    db = SessionLocal()
    try:
        ok = try_resolve_local_demo_user(
            db, "demo@bharathi.local", _DEMO_PASSWORD, "Store Manager"
        )
        assert ok.kind == "ok"
        assert ok.user is not None
        assert ok.user.email == LOCAL_DEMO_ACCOUNT_EMAIL_BY_ROLE["Store Manager"]
    finally:
        db.close()


def test_store_manager_demo_cannot_use_admin_api(client, demo_login_env):
    _seed_demo_users()
    login = client.post(
        "/auth/login",
        json={
            "email": "demo@bharathi.local",
            "password": _DEMO_PASSWORD,
            "role": "Store Manager",
        },
    )
    assert login.status_code == 200
    assert login.json().get("user", {}).get("role") == "Store Manager"
    denied = client.get("/admin/users")
    assert denied.status_code in (403, 404, 401)