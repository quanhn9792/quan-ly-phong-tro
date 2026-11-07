from __future__ import annotations

import pytest

from src import queries as q

from .conftest import csrf_from

OWNER_PAGES = ["/", "/bills/new", "/reports", "/reports/zalo", "/tenants", "/rooms", "/properties", "/months",
               "/payment-settings", "/account"]


# ----- Đăng nhập / bảo mật -----

@pytest.mark.parametrize("path", OWNER_PAGES)
def test_pages_require_login(app, path):
    response = app.test_client().get(path)
    assert response.status_code == 302 and "/login" in response.headers["Location"]


@pytest.mark.parametrize("path", OWNER_PAGES)
def test_owner_pages_render(owner, path):
    response = owner.get(path)
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "private, no-store"


def test_post_without_csrf_is_rejected(owner):
    assert owner.post("/select-property", data={"property_id": ""}).status_code == 400
    assert owner.post("/select-property", data={"property_id": "", "csrf_token": owner.csrf}).status_code == 302


def test_wrong_password_and_lockout(app):
    client = app.test_client()
    token = csrf_from(client.get("/login").get_data(as_text=True))
    for _ in range(5):
        client.post("/login", data={"username": "lockme", "password": "sai", "csrf_token": token})
    html = client.post("/login", data={"username": "lockme", "password": "sai", "csrf_token": token}).get_data(as_text=True)
    assert "quá nhiều lần" in html


def test_login_next_is_not_open_redirect(app):
    assert app.test_client().get("/login?next=//evil.example").status_code == 200


def test_public_pwa_files(app):
    client = app.test_client()
    for path in ["/manifest.webmanifest", "/sw.js", "/offline", "/static/icons/icon-192.png"]:
        assert client.get(path).status_code == 200, path
    assert client.get("/.well-known/assetlinks.json").status_code == 404  # chưa cấu hình


def test_gzip(owner):
    response = owner.get("/static/styles.css", headers={"Accept-Encoding": "gzip"})
    assert response.headers.get("Content-Encoding") == "gzip"


# ----- Thu tiền -----

def test_mark_paid_and_unpaid(owner):
    bill = q.month_bills(2026, 11)[0]
    response = owner.post(f"/reports/bills/{bill.RoomMonthlyBillId}/paid", data={"paid": "1", "csrf_token": owner.csrf},
                          headers={"X-Requested-With": "fetch"})
    assert response.get_json() == {"paid": True}
    assert q.get_bill(bill.RoomMonthlyBillId).PaidAt is not None
    owner.post(f"/reports/bills/{bill.RoomMonthlyBillId}/paid", data={"paid": "0", "csrf_token": owner.csrf})
    assert q.get_bill(bill.RoomMonthlyBillId).PaidAt is None


def test_overdue_lists_previous_months_only(app):
    assert q.unpaid_bills_before(2026, 11) == []
    assert len(q.unpaid_bills_before(2026, 12)) == 2


# ----- App của khách -----

def test_tenant_portal_flow(owner, app):
    tenant = q.tenant_list()[0]
    owner.post(f"/tenants/{tenant.TenantId}/portal-link", data={"action": "create", "csrf_token": owner.csrf})
    token = q.tenant_portal_token(tenant.TenantId)
    assert token and len(token) >= 43

    guest = app.test_client()
    home = guest.get(f"/k/{token}")
    assert home.status_code == 200 and "Set-Cookie" not in home.headers
    own_bill = q.tenant_bills(q.tenant_by_portal_token(token))[0]
    other_bill = next(b for b in q.month_bills(2026, 11) if b.RoomId != tenant.RoomId)
    assert guest.get(f"/k/{token}/hoa-don/{own_bill.RoomMonthlyBillId}").status_code == 200
    assert guest.get(f"/k/{token}/hoa-don/{own_bill.RoomMonthlyBillId}/qr.png").mimetype == "image/png"
    assert guest.get(f"/k/{token}/hoa-don/{other_bill.RoomMonthlyBillId}").status_code == 404
    assert guest.get(f"/k/{token}/manifest.webmanifest").get_json()["start_url"] == f"/k/{token}"

    owner.post(f"/tenants/{tenant.TenantId}/portal-link", data={"action": "revoke", "csrf_token": owner.csrf})
    assert guest.get(f"/k/{token}").status_code == 404


def test_guest_cannot_use_owner_routes(app):
    assert app.test_client().get("/reports/bills/1/notice.png").status_code == 302


# ----- Ảnh hóa đơn -----

def test_notice_image_and_thumbnail(owner):
    bill = q.month_bills(2026, 11)[0]
    assert owner.get(f"/reports/bills/{bill.RoomMonthlyBillId}/notice.png").mimetype == "image/png"
    thumb = owner.get(f"/reports/bills/{bill.RoomMonthlyBillId}/thumb.jpg")
    assert thumb.mimetype == "image/jpeg" and len(thumb.data) < 40_000
