"""Test chạy trên database riêng QuanLyPhongTro_PyTest (tạo mới mỗi lần), không đụng dữ liệu thật.

    pip install -r requirements-dev.txt
    pytest
"""
from __future__ import annotations

import os
import re
from datetime import date
from decimal import Decimal as D

import pytest

TEST_DB = "QuanLyPhongTro_PyTest"
os.environ["MSSQL_DATABASE"] = TEST_DB
# Không để cấu hình thật trong instance/web.env (tunnel, PUBLIC_URL...) ảnh hưởng tới test
for _key in ("PUBLIC_URL", "TRUST_PROXY", "ANDROID_PACKAGE", "ANDROID_CERT_SHA256", "TEMPLATES_AUTO_RELOAD"):
    os.environ[_key] = ""

from src import auth  # noqa: E402
from src import queries as q  # noqa: E402
from src.db import connect, init_database  # noqa: E402
from src.web import create_app  # noqa: E402

PASSWORD = "matkhau-test-123"


def _recreate_database() -> None:
    with connect(database="master", autocommit=True) as cnxn:
        cnxn.cursor().execute(
            f"IF DB_ID(N'{TEST_DB}') IS NOT NULL BEGIN "
            f"ALTER DATABASE [{TEST_DB}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE; DROP DATABASE [{TEST_DB}]; END"
        )
    init_database()


@pytest.fixture(scope="session")
def app():
    try:
        _recreate_database()
    except Exception as exc:  # không có SQL Server trên máy
        pytest.skip(f"Không kết nối được SQL Server: {exc}")
    auth.set_owner_password("admin", PASSWORD)
    pid = q.save_property(None, "Nhà test", "ROOMING_HOUSE", None, None)
    for i in (1, 2):
        rid = q.create_room(pid, f"P0{i}", f"Phòng {i}", D(3000000), D(100000), D(0), D(4000), D(25000))
        q.save_tenant(None, {"RoomId": rid, "FullName": f"Khách {i}", "ZaloPhone": f"090000000{i}",
                             "MoveInDate": date(2026, 1, 1), "RentAmount": D(3000000), "IsCurrent": 1})
        q.sync_room_status(rid)
        q.save_bill(q.get_room(rid), 2026, 11, D(0), D(50), D(0), D(5), None)
    application = create_app()
    application.config["TESTING"] = True
    return application


def csrf_from(html: str) -> str:
    match = re.search(r'name="csrf[-_]token" (?:value|content)="([^"]+)"', html)
    assert match, "trang không có CSRF token"
    return match.group(1)


@pytest.fixture
def owner(app):
    """Client đã đăng nhập; client.csrf là token để gửi form."""
    client = app.test_client()
    token = csrf_from(client.get("/login").get_data(as_text=True))
    response = client.post("/login", data={"username": "admin", "password": PASSWORD, "csrf_token": token})
    assert response.status_code == 302
    client.csrf = csrf_from(client.get("/").get_data(as_text=True))
    return client


@pytest.fixture(autouse=True)
def reset_login_throttle():
    yield
    auth._failures.clear()  # test chặn dò mật khẩu khóa cả IP 127.0.0.1
