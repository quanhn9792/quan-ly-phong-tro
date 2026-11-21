"""Test cho các lỗi tìm được khi review code (mục 1–8)."""
from __future__ import annotations

from datetime import date
from decimal import Decimal as D

import pytest

from src import auth
from src import queries as q
from src.portal import new_token

from .conftest import PASSWORD, csrf_from


# ----- 1. Chuyển hướng ra trang ngoài -----

@pytest.mark.parametrize("evil", ["/\t/evil.example", "/\n/evil.example", "/\r/evil.example", "//evil.example",
                                  "/\\evil.example", "https://evil.example", "/\x7f/evil.example"])
def test_safe_next_rejects_tricks(evil):
    assert auth.safe_next(evil) is None


@pytest.mark.parametrize("ok", ["/rooms", "/reports?year=2026&month=11", "/k/abc"])
def test_safe_next_keeps_internal_paths(ok):
    assert auth.safe_next(ok) == ok


def test_login_next_with_tab_does_not_leave_site(app):
    client = app.test_client()
    token = csrf_from(client.get("/login").get_data(as_text=True))
    response = client.post("/login", data={"username": "admin", "password": PASSWORD, "csrf_token": token,
                                           "next": "/\t/evil.example"})
    assert response.status_code == 302 and "evil.example" not in response.headers["Location"]
    assert client.get("/login?next=/%0a").status_code in (200, 302)  # trước đây lỗi 500


# ----- 2 & 3. Cổng khách: không lộ thông tin khách khác, thu hồi link khi chuyển đi -----

@pytest.fixture
def handover(owner):
    """Phòng mới: khách A ở đến 10/11/2026, khách B vào 15/11/2026, cùng một hóa đơn tháng 11."""
    pid = q.property_list()[0].PropertyId
    rid = q.create_room(pid, f"H{new_token()[:6]}", "Phòng đổi khách", D(2000000), D(0), D(0), D(4000), D(25000))
    q.save_tenant(None, {"RoomId": rid, "FullName": "Khách A cũ", "Phone": "0911111111", "Email": "a@vd.vn",
                         "MoveInDate": date(2026, 1, 1), "MoveOutDate": date(2026, 11, 10), "IsCurrent": 1})
    q.save_tenant(None, {"RoomId": rid, "FullName": "Khách B mới", "Phone": "0922222222", "Email": "b@bimat.vn",
                         "MoveInDate": date(2026, 11, 15), "IsCurrent": 1})
    q.save_bill(q.get_room(rid), 2026, 11, D(0), D(10), D(0), D(1), None)
    tenants = {t.FullName: t for t in q.tenant_list() if t.RoomId == rid}
    for tenant in tenants.values():
        q.set_tenant_portal_token(tenant.TenantId, new_token())
    tokens = {name: q.tenant_portal_token(t.TenantId) for name, t in tenants.items()}
    return rid, tokens, tenants


def test_portal_hides_other_tenants_contact(app, handover):
    rid, tokens, _ = handover
    bill = q.bill_for_room_month(rid, 2026, 11)
    guest = app.test_client()
    for path in (f"/k/{tokens['Khách A cũ']}/hoa-don/{bill.RoomMonthlyBillId}", f"/k/{tokens['Khách A cũ']}"):
        html = guest.get(path).get_data(as_text=True)
        assert "0922222222" not in html and "b@bimat.vn" not in html and "Khách B mới" not in html
    html = guest.get(f"/k/{tokens['Khách B mới']}/hoa-don/{bill.RoomMonthlyBillId}").get_data(as_text=True)
    assert "Khách B mới" in html and "Khách A cũ" not in html and "0911111111" not in html


def test_end_tenancy_revokes_link(owner, app, handover):
    _, tokens, tenants = handover
    owner.post(f"/tenants/{tenants['Khách A cũ'].TenantId}/end", data={"csrf_token": owner.csrf})
    assert q.tenant_portal_token(tenants["Khách A cũ"].TenantId) is None
    assert app.test_client().get(f"/k/{tokens['Khách A cũ']}").status_code == 404


def test_past_tenant_old_token_rejected(app, handover):
    _, tokens, tenants = handover
    q.save_tenant(tenants["Khách A cũ"].TenantId, {"IsCurrent": 0})  # dữ liệu cũ: ngưng thuê nhưng còn token
    assert app.test_client().get(f"/k/{tokens['Khách A cũ']}").status_code == 404


def test_moving_room_revokes_link(owner, handover):
    rid, _, tenants = handover
    other_room = next(r for r in q.room_list() if r.RoomId != rid)
    tenant = tenants["Khách B mới"]
    owner.post(f"/tenants/{tenant.TenantId}", data={
        "csrf_token": owner.csrf, "room_id": other_room.RoomId, "full_name": tenant.FullName,
        "rent_amount": "0", "service_fee": "0", "is_current": "1", "move_in_date": "2026-11-15",
    })
    assert q.tenant_portal_token(tenant.TenantId) is None


def test_tenant_without_move_in_starts_from_record_creation():
    room = q.room_list()[0]
    q.save_tenant(None, {"RoomId": room.RoomId, "FullName": "Khách không ngày 2", "IsCurrent": 1})
    tenant = next(t for t in q.tenant_list() if t.FullName == "Khách không ngày 2")
    q.set_tenant_portal_token(tenant.TenantId, new_token())
    bills = q.tenant_bills(q.tenant_by_portal_token(q.tenant_portal_token(tenant.TenantId)))
    first_of_month = date.today().replace(day=1)
    assert all(date(b.YearNumber, b.MonthNumber, 1) >= first_of_month for b in bills)


# ----- 4. Người lạ không khóa được chủ nhà -----

def test_trusted_device_can_login_while_locked(app):
    owner_device = app.test_client()
    token = csrf_from(owner_device.get("/login").get_data(as_text=True))
    owner_device.post("/login", data={"username": "admin", "password": PASSWORD, "csrf_token": token})
    owner_device.post("/logout", data={"csrf_token": csrf_from(owner_device.get("/").get_data(as_text=True))})

    attacker = app.test_client()
    token = csrf_from(attacker.get("/login").get_data(as_text=True))
    for _ in range(6):
        attacker.post("/login", data={"username": "admin", "password": "sai", "csrf_token": token})
    html = attacker.post("/login", data={"username": "admin", "password": PASSWORD, "csrf_token": token}).get_data(as_text=True)
    assert "quá nhiều lần" in html  # kẻ lạ (không có cookie thiết bị) vẫn bị khóa

    token = csrf_from(owner_device.get("/login").get_data(as_text=True))
    response = owner_device.post("/login", data={"username": "admin", "password": PASSWORD, "csrf_token": token})
    assert response.status_code == 302  # thiết bị quen của chủ nhà vẫn vào được


def test_trusted_device_invalid_after_password_change(app):
    device = app.test_client()
    token = csrf_from(device.get("/login").get_data(as_text=True))
    device.post("/login", data={"username": "admin", "password": PASSWORD, "csrf_token": token})
    auth.set_owner_password("admin", PASSWORD)  # hash mới => cookie thiết bị cũ hết hiệu lực
    user = auth.get_user_by_username("admin")
    with app.test_request_context(headers={"Cookie": f"{auth.DEVICE_COOKIE}={device.get_cookie(auth.DEVICE_COOKIE).value}"}):
        assert not auth.trusted_device_for(user)


def test_throttle_memory_is_capped(monkeypatch):
    monkeypatch.setattr(auth, "MAX_TRACKED_KEYS", 50)
    for i in range(200):
        auth.record_failure([f"user:x{i}"])
    assert len(auth._failures) <= 51


# ----- 5. Không lưu offline trang nhạy cảm, đăng xuất xóa Cache Storage -----

def test_service_worker_skips_sensitive_pages(app):
    sw = app.test_client().get("/sw.js").get_data(as_text=True)
    for path in ("/tenants", "/payment-settings", "/account"):
        assert f'"{path}"' in sw
    assert "MAX_PAGE_AGE_MS" in sw


def test_logout_clears_storage(owner):
    response = owner.post("/logout", data={"csrf_token": owner.csrf})
    assert '"storage"' in response.headers.get("Clear-Site-Data", "")


# ----- 6. Từ chối khi khách báo nhầm -----

def test_owner_can_reject_tenant_report(owner, app, handover):
    rid, tokens, _ = handover
    bill = q.bill_for_room_month(rid, 2026, 11)
    guest = app.test_client()
    guest.post(f"/k/{tokens['Khách B mới']}/hoa-don/{bill.RoomMonthlyBillId}/da-chuyen")
    assert "Chưa nhận được" in owner.get("/").get_data(as_text=True)
    owner.post(f"/reports/bills/{bill.RoomMonthlyBillId}/reject-report", data={"csrf_token": owner.csrf})
    assert q.get_bill(bill.RoomMonthlyBillId).TenantReportedPaidAt is None
    page = guest.get(f"/k/{tokens['Khách B mới']}/hoa-don/{bill.RoomMonthlyBillId}").get_data(as_text=True)
    assert "Tôi đã chuyển khoản" in page  # khách báo lại được


# ----- 7. Sửa hóa đơn đã thu -----

def test_editing_paid_bill_resets_status_when_total_changes(owner, handover):
    rid, _, _ = handover
    bill = q.bill_for_room_month(rid, 2026, 11)
    q.set_bill_paid(bill.RoomMonthlyBillId, True)
    owner.post(f"/bills/new?year=2026&month=11&room_id={rid}", data={
        "csrf_token": owner.csrf, "electric_old": "0", "electric_new": "50", "water_old": "0", "water_new": "1",
    })
    assert q.get_bill(bill.RoomMonthlyBillId).PaidAt is None


def test_editing_paid_bill_keeps_status_when_total_same(owner, handover):
    rid, _, _ = handover
    bill = q.bill_for_room_month(rid, 2026, 11)
    q.set_bill_paid(bill.RoomMonthlyBillId, True)
    owner.post(f"/bills/new?year=2026&month=11&room_id={rid}", data={
        "csrf_token": owner.csrf, "electric_old": str(bill.ElectricOld), "electric_new": str(bill.ElectricNew),
        "water_old": str(bill.WaterOld), "water_new": str(bill.WaterNew), "note": "chỉ sửa ghi chú",
    })
    assert q.get_bill(bill.RoomMonthlyBillId).PaidAt is not None


def test_repricing_resets_paid_and_keeps_vacant_months_utilities_only():
    pid = q.property_list()[0].PropertyId
    rid = q.create_room(pid, f"G{new_token()[:6]}", "Phòng đổi giá", D(1000000), D(0), D(0), D(4000), D(25000))
    q.save_bill(q.get_room(rid), 2026, 10, D(0), D(10), D(0), D(1), None)  # phòng trống: chỉ điện nước
    vacant = q.bill_for_room_month(rid, 2026, 10)
    assert vacant.RentAmount == 0
    q.save_tenant(None, {"RoomId": rid, "FullName": "Khách đổi giá", "MoveInDate": date(2026, 11, 1),
                         "RentAmount": D(1000000), "IsCurrent": 1})
    q.save_bill(q.get_room(rid), 2026, 11, D(10), D(20), D(1), D(2), None)
    paid = q.bill_for_room_month(rid, 2026, 11)
    q.set_bill_paid(paid.RoomMonthlyBillId, True)
    q.update_room_prices(rid, D(1500000), D(0), D(0), D(4000), D(25000), "VACANT", 2026, 10, None, None)
    assert q.get_bill(vacant.RoomMonthlyBillId).RentAmount == 0       # tháng trống vẫn không tính tiền thuê
    after = q.get_bill(paid.RoomMonthlyBillId)
    assert after.RentAmount == D(1500000) and after.PaidAt is None    # đổi giá => chuyển về chưa thu


# ----- 8. Trang khách khi DB tắt -----

def test_portal_db_down_shows_friendly_page(app, monkeypatch):
    import pyodbc

    from src import portal

    def boom(*_args, **_kwargs):
        raise pyodbc.Error("08001", "SECRET-SERVER")

    monkeypatch.setattr(portal.q, "tenant_by_portal_token", boom)
    monkeypatch.setattr(portal.q, "payment_settings", boom)
    response = app.test_client().get("/k/" + "a" * 43)
    assert response.status_code == 503 and "SECRET-SERVER" not in response.get_data(as_text=True)
