"""Đăng nhập, phiên làm việc và chống CSRF.

Bắt buộc khi mở web ra Internet (Tailscale Funnel / Cloudflare Tunnel) để dùng trên điện thoại.
Tài khoản chủ nhà chỉ tạo được bằng lệnh `python main.py create-owner` — không có trang "đăng ký"
vì qua tunnel mọi request đều tới từ 127.0.0.1, không phân biệt được người ở máy chủ với người lạ.
"""
from __future__ import annotations

import secrets
import threading
import time
from collections import defaultdict, deque
from datetime import timedelta
from typing import Any

from flask import Flask, abort, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from .db import execute, one

MIN_PASSWORD_LENGTH = 8
SESSION_DAYS = 30
CSRF_FIELD = "csrf_token"
CSRF_HEADER = "X-CSRF-Token"
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
# Các trang mở được khi chưa đăng nhập
PUBLIC_ENDPOINTS = {"login", "static", "service_worker", "manifest", "offline_page"}

# Chặn dò mật khẩu: tối đa 5 lần sai / 15 phút cho mỗi IP và mỗi tên đăng nhập
MAX_FAILURES = 5
FAILURE_WINDOW_SECONDS = 15 * 60
_failures: dict[str, deque[float]] = defaultdict(deque)
_failures_lock = threading.Lock()


# ----- Tài khoản -----

def get_user(user_id: int) -> Any | None:
    return one(
        "SELECT UserId, Username, PasswordHash, UserRole FROM dbo.AppUsers WHERE UserId = ? AND IsActive = 1;",
        (user_id,),
    )


def get_user_by_username(username: str) -> Any | None:
    return one(
        "SELECT UserId, Username, PasswordHash, UserRole FROM dbo.AppUsers WHERE Username = ? AND IsActive = 1;",
        (username,),
    )


def has_any_user() -> bool:
    return one("SELECT TOP (1) 1 FROM dbo.AppUsers WHERE IsActive = 1;") is not None


def set_owner_password(username: str, password: str) -> bool:
    """Tạo tài khoản chủ nhà hoặc đổi mật khẩu nếu đã có. Trả về True nếu là tài khoản mới."""
    username = username.strip()
    if not username or len(username) > 50:
        raise ValueError("Tên đăng nhập phải từ 1–50 ký tự.")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Mật khẩu phải có ít nhất {MIN_PASSWORD_LENGTH} ký tự.")
    password_hash = generate_password_hash(password)
    updated = execute(
        "UPDATE dbo.AppUsers SET PasswordHash = ?, IsActive = 1, UpdatedAt = SYSDATETIME() WHERE Username = ?;",
        (password_hash, username),
    )
    if updated:
        return False
    execute(
        "INSERT INTO dbo.AppUsers (Username, PasswordHash, UserRole) VALUES (?, ?, N'OWNER');",
        (username, password_hash),
    )
    return True


def password_version(user: Any) -> str:
    # Đổi mật khẩu => hash đổi => mọi phiên đăng nhập cũ (kể cả trên điện thoại bị mất) hết hiệu lực
    return user.PasswordHash[-16:]


# ----- Chặn dò mật khẩu -----

def _recent(key: str, now: float) -> deque[float]:
    attempts = _failures[key]
    while attempts and now - attempts[0] > FAILURE_WINDOW_SECONDS:
        attempts.popleft()
    return attempts


def login_blocked(keys: list[str]) -> bool:
    now = time.monotonic()
    with _failures_lock:
        return any(len(_recent(key, now)) >= MAX_FAILURES for key in keys)


def record_failure(keys: list[str]) -> None:
    now = time.monotonic()
    with _failures_lock:
        for key in keys:
            _recent(key, now).append(now)


def clear_failures(keys: list[str]) -> None:
    with _failures_lock:
        for key in keys:
            _failures.pop(key, None)


# ----- CSRF -----

def csrf_token() -> str:
    token = session.get(CSRF_FIELD)
    if not token:
        token = secrets.token_urlsafe(32)
        session[CSRF_FIELD] = token
    return token


def csrf_valid() -> bool:
    expected = session.get(CSRF_FIELD)
    sent = request.form.get(CSRF_FIELD) or request.headers.get(CSRF_HEADER)
    return bool(expected and sent and secrets.compare_digest(str(expected), str(sent)))


def safe_next(target: str | None) -> str | None:
    return target if target and target.startswith("/") and not target.startswith("//") and "\\" not in target else None


# ----- Gắn vào app -----

def register_auth(app: Flask) -> None:
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        PERMANENT_SESSION_LIFETIME=timedelta(days=SESSION_DAYS),
    )
    app.jinja_env.globals["csrf_token"] = csrf_token

    @app.before_request
    def require_login():
        g.user = None
        if request.endpoint in ("static", "service_worker", "manifest"):
            return None  # file tĩnh: không cần tra DB
        user_id = session.get("user_id")
        if user_id:
            user = get_user(int(user_id))
            if user is not None and session.get("pwv") == password_version(user):
                g.user = user
            else:
                session.clear()

        if request.method in UNSAFE_METHODS and not csrf_valid():
            abort(400, description="Phiên làm việc đã hết hạn, hãy tải lại trang rồi thử lại.")

        if g.user is None and request.endpoint not in PUBLIC_ENDPOINTS:
            if request.method in ("GET", "HEAD"):
                return redirect(url_for("login", next=request.full_path.rstrip("?")))
            abort(401)
        return None

    @app.after_request
    def security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        if g.get("user") is not None and request.endpoint != "static":
            # Không để trình duyệt/proxy lưu trang chứa dữ liệu khách thuê
            response.headers.setdefault("Cache-Control", "private, no-store")
        return response

    @app.route("/login", methods=["GET", "POST"])
    def login():
        next_url = safe_next(request.values.get("next")) or url_for("dashboard")
        if g.user is not None:
            return redirect(next_url)

        no_user = not has_any_user()
        if request.method == "POST" and not no_user:
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            keys = [f"ip:{request.remote_addr}", f"user:{username.lower()}"]
            if login_blocked(keys):
                flash("Đăng nhập sai quá nhiều lần. Hãy thử lại sau 15 phút.", "error")
            else:
                user = get_user_by_username(username) if username else None
                if user is not None and check_password_hash(user.PasswordHash, password):
                    clear_failures(keys)
                    session.clear()
                    session.permanent = request.form.get("remember") == "1"
                    session["user_id"] = int(user.UserId)
                    session["pwv"] = password_version(user)
                    execute("UPDATE dbo.AppUsers SET LastLoginAt = SYSDATETIME() WHERE UserId = ?;", (user.UserId,))
                    return redirect(next_url)
                record_failure(keys)
                flash("Sai tên đăng nhập hoặc mật khẩu.", "error")
        return render_template("login.html", next_url=next_url, no_user=no_user)

    @app.route("/account", methods=["GET", "POST"])
    def account_page():
        if request.method == "POST":
            current = request.form.get("current_password", "")
            new = request.form.get("new_password", "")
            if not check_password_hash(g.user.PasswordHash, current):
                flash("Mật khẩu hiện tại không đúng.", "error")
            elif new != request.form.get("confirm_password", ""):
                flash("Hai lần nhập mật khẩu mới không khớp.", "error")
            else:
                try:
                    set_owner_password(g.user.Username, new)
                except ValueError as exc:
                    flash(str(exc), "error")
                else:
                    # Giữ đăng nhập trên thiết bị này, các thiết bị khác bị đăng xuất
                    session["pwv"] = password_version(get_user(int(g.user.UserId)))
                    flash("Đã đổi mật khẩu. Các thiết bị khác đã bị đăng xuất.", "success")
                    return redirect(url_for("account_page"))
        return render_template("account.html", min_length=MIN_PASSWORD_LENGTH)

    @app.post("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))
