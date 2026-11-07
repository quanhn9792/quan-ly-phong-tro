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


def test_post_without_csrf_is_rejected(owner, app):
    property_id = q.property_list()[0].PropertyId
    owner.post("/select-property", data={"property_id": str(property_id)})  # thiếu token
    with owner.session_transaction() as sess:
        assert "property_id" not in sess
    owner.post("/select-property", data={"property_id": str(property_id), "csrf_token": owner.csrf})
    with owner.session_transaction() as sess:
        assert sess["property_id"] == property_id
    owner.post("/select-property", data={"property_id": "", "csrf_token": owner.csrf})
    assert app.test_client().post("/select-property", data={"property_id": ""}).status_code == 400


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
        with client.get(path) as response:
            assert response.status_code == 200, path
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


def test_tenant_reports_paid_then_owner_confirms(owner, app):
    tenant = q.tenant_list()[1]
    owner.post(f"/tenants/{tenant.TenantId}/portal-link", data={"action": "create", "csrf_token": owner.csrf})
    token = q.tenant_portal_token(tenant.TenantId)
    bill = q.tenant_bills(q.tenant_by_portal_token(token))[0]
    guest = app.test_client()
    page = guest.get(f"/k/{token}/hoa-don/{bill.RoomMonthlyBillId}").get_data(as_text=True)
    assert "Tôi đã chuyển khoản" in page
    # Không cần phiên/CSRF: mã bí mật trong link là khóa
    response = guest.post(f"/k/{token}/hoa-don/{bill.RoomMonthlyBillId}/da-chuyen")
    assert response.status_code == 302
    assert q.get_bill(bill.RoomMonthlyBillId).TenantReportedPaidAt is not None
    assert "Khách báo đã chuyển khoản" in owner.get("/").get_data(as_text=True)
    # Mã sai / hóa đơn phòng khác: không ghi được
    other = next(b for b in q.month_bills(2026, 11) if b.RoomId != tenant.RoomId)
    assert guest.post(f"/k/{token}/hoa-don/{other.RoomMonthlyBillId}/da-chuyen").status_code == 404
    assert q.get_bill(other.RoomMonthlyBillId).TenantReportedPaidAt is None
    owner.post(f"/reports/bills/{bill.RoomMonthlyBillId}/paid", data={"paid": "1", "csrf_token": owner.csrf})
    assert "Khách báo đã chuyển khoản" not in owner.get("/").get_data(as_text=True)


def test_error_pages_are_friendly(app, owner):
    guest = app.test_client()
    response = guest.get("/k/" + "x" * 43)
    assert response.status_code == 404 and "bị thu hồi" in response.get_data(as_text=True)
    # Phiên hết hạn khi đang gửi form: báo lỗi dễ hiểu rồi quay lại trang, không hiện trang 400 trống
    response = owner.post("/select-property", data={"property_id": ""}, headers={"Referer": "/rooms"})
    assert response.status_code == 302


def test_db_error_details_hidden_from_guests(app, monkeypatch):
    import pyodbc

    from src import portal

    def boom(token):
        raise pyodbc.Error("08001", "SECRET-SERVER-NAME")

    monkeypatch.setattr(portal.q, "tenant_by_portal_token", boom)
    response = app.test_client().get("/k/" + "a" * 43)
    assert response.status_code == 503
    assert "SECRET-SERVER-NAME" not in response.get_data(as_text=True)


def test_portal_for_tenant_without_dates(owner, app):
    room = q.room_list()[0]
    q.save_tenant(None, {"RoomId": room.RoomId, "FullName": "Khách không ngày", "IsCurrent": 1})
    tenant = next(t for t in q.tenant_list() if t.FullName == "Khách không ngày")
    owner.post(f"/tenants/{tenant.TenantId}/portal-link", data={"action": "create", "csrf_token": owner.csrf})
    token = q.tenant_portal_token(tenant.TenantId)
    bills = q.tenant_bills(q.tenant_by_portal_token(token))
    assert bills, "khách không có ngày vào/ra phải thấy mọi hóa đơn của phòng"
    assert app.test_client().get(f"/k/{token}").status_code == 200
    # khách đã chuyển đi trước tháng 11: không thấy hóa đơn tháng 11
    q.save_tenant(tenant.TenantId, {"MoveInDate": "2025-01-01", "MoveOutDate": "2025-12-31", "IsCurrent": 0})
    assert q.tenant_bills(q.tenant_by_portal_token(token)) == []


def test_export_csv(owner):
    response = owner.get("/reports/export.csv?year=2026&month=11")
    assert response.status_code == 200 and response.mimetype == "text/csv"
    text = response.data.decode("utf-8-sig")
    assert text.splitlines()[0].startswith("Nhà,Phòng/căn")
    assert len(text.strip().splitlines()) == 1 + len(q.month_bills(2026, 11))


def test_asset_version_matches_service_worker(owner, app):
    import re as _re

    page = owner.get("/").get_data(as_text=True)
    version = _re.search(r"styles\.css\?v=([0-9a-f]{10})", page).group(1)
    sw = app.test_client().get("/sw.js").get_data(as_text=True)
    assert f'const VERSION = "{version}"' in sw and "__ASSET_VERSION__" not in sw
    assert f"app.js?v={version}" in page


def test_create_all_portal_links(owner):
    owner.post("/tenants/portal-links", data={"csrf_token": owner.csrf})
    assert all(t.PortalToken for t in q.tenant_list() if t.IsCurrent)


def test_session_cookie_secure_only_over_https(app):
    from .conftest import PASSWORD

    for scheme, secure in (("http", False), ("https", True)):
        client = app.test_client()
        base = f"{scheme}://localhost"
        token = csrf_from(client.get(base + "/login").get_data(as_text=True))
        response = client.post(base + "/login", data={"username": "admin", "password": PASSWORD, "csrf_token": token})
        cookie = response.headers.get("Set-Cookie", "")
        assert ("Secure" in cookie) is secure, cookie


def test_install_page(owner, monkeypatch):
    html = owner.get("/install").get_data(as_text=True)
    assert "Chưa có địa chỉ" in html  # mở bằng localhost, chưa có PUBLIC_URL
    assert owner.get("/install/qr.png").status_code == 404
    monkeypatch.setenv("PUBLIC_URL", "https://nha.example.ts.net")
    assert "https://nha.example.ts.net" in owner.get("/install").get_data(as_text=True)
    assert owner.get("/install/qr.png").mimetype == "image/png"


def test_owner_phone_shown_in_portal(owner, app):
    from src.notify import normalize_phone

    assert normalize_phone("+84 912 345 678") == "0912345678" and normalize_phone("12") is None
    owner.post("/payment-settings", data={"settings_type": "qr", "account_info": "", "owner_phone": "+84 912 345 678",
                                          "csrf_token": owner.csrf})
    tenant = q.tenant_list()[0]
    owner.post(f"/tenants/{tenant.TenantId}/portal-link", data={"action": "create", "csrf_token": owner.csrf})
    html = app.test_client().get(f"/k/{q.tenant_portal_token(tenant.TenantId)}").get_data(as_text=True)
    assert 'href="tel:0912345678"' in html and "zalo.me/0912345678" in html


def test_property_switcher_and_no_open_redirect(owner):
    if len(q.property_list()) < 2:
        q.save_property(None, "Nhà thứ hai", "APARTMENT", None, None)
    assert 'class="appbar-switch"' in owner.get("/").get_data(as_text=True)
    for evil in ("//evil.example", "/\evil.example", "https://evil.example"):
        response = owner.post("/select-property", data={"property_id": "", "next": evil, "csrf_token": owner.csrf})
        assert "evil.example" not in response.headers["Location"], evil
    response = owner.post("/select-property", data={"property_id": "", "next": "/rooms", "csrf_token": owner.csrf})
    assert response.headers["Location"].endswith("/rooms")


def test_bill_detail_shows_report_and_app_link(owner, app):
    tenant = q.tenant_list()[0]
    owner.post(f"/tenants/{tenant.TenantId}/portal-link", data={"action": "create", "csrf_token": owner.csrf})
    token = q.tenant_portal_token(tenant.TenantId)
    bill = q.tenant_bills(q.tenant_by_portal_token(token))[0]
    q.set_bill_paid(bill.RoomMonthlyBillId, False)
    app.test_client().post(f"/k/{token}/hoa-don/{bill.RoomMonthlyBillId}/da-chuyen")
    html = owner.get(f"/reports/bills/{bill.RoomMonthlyBillId}").get_data(as_text=True)
    assert "Khách báo đã chuyển khoản lúc" in html and f"/k/{token}" in html


def test_cookie_secure_behind_tunnel_without_forwarded_proto(app, monkeypatch):
    monkeypatch.setenv("TRUST_PROXY", "1")
    monkeypatch.setenv("PUBLIC_URL", "https://nha.example.ts.net")
    client = app.test_client()
    tunnel = client.get("/login", base_url="http://nha.example.ts.net")  # Tailscale Funnel: không có X-Forwarded-Proto
    assert "Secure" in tunnel.headers.get("Set-Cookie", "")
    local = app.test_client().get("/login", base_url="http://127.0.0.1:5000")
    assert "Secure" not in local.headers.get("Set-Cookie", "")
