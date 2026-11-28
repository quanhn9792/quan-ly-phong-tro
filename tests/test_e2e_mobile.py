"""Test giao diện điện thoại thật bằng Playwright (Chromium ~ Android, WebKit ~ iPhone Safari).

    pip install -r requirements-dev.txt
    python -m playwright install chromium webkit
    pytest tests/test_e2e_mobile.py

Tự bỏ qua nếu chưa cài Playwright / trình duyệt.
"""
from __future__ import annotations

import threading

import pytest

from src import queries as q

from .conftest import PASSWORD

playwright_api = pytest.importorskip("playwright.sync_api")


@pytest.fixture(scope="module")
def base_url(app):
    from werkzeug.serving import make_server

    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


@pytest.fixture(scope="module", params=["chromium", "webkit"])
def phone(request):
    with playwright_api.sync_playwright() as p:
        try:
            browser = getattr(p, request.param).launch()
        except Exception as exc:  # trình duyệt chưa được cài
            pytest.skip(f"Chưa cài {request.param}: {exc}")
        device = p.devices["iPhone 13"] if request.param == "webkit" else p.devices["Pixel 7"]
        yield browser, device
        browser.close()


def login(page, base_url):
    page.goto(base_url + "/login")
    page.fill("input[name=username]", "admin")
    page.fill("input[name=password]", PASSWORD)
    page.click("button[type=submit]")
    # Chờ hẳn tới khi rời trang đăng nhập (networkidle có thể xong trước khi chuyển trang)
    page.wait_for_url(lambda url: "/login" not in url)
    page.wait_for_load_state("networkidle")


def no_overflow(page) -> bool:
    return page.evaluate("document.documentElement.scrollWidth - innerWidth") <= 0


def test_owner_pages_fit_phone(phone, base_url):
    browser, device = phone
    page = browser.new_context(**device).new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    login(page, base_url)
    for path in ["/", "/bills/new", "/reports?year=2026&month=11", "/reports/zalo?year=2026&month=11", "/tenants", "/install"]:
        page.goto(base_url + path)
        page.wait_for_load_state("networkidle")
        assert no_overflow(page), f"tràn ngang ở {path}"
    assert not errors


def test_menu_opens_and_closes_by_tapping_outside(phone, base_url):
    browser, device = phone
    page = browser.new_context(**device).new_page()
    login(page, base_url)
    page.locator("[data-menu-toggle]").tap()
    page.wait_for_timeout(300)
    assert page.evaluate("document.body.classList.contains('menu-open')")
    page.touchscreen.tap(15, 300)  # vùng tối bên trái menu
    page.wait_for_timeout(300)
    assert not page.evaluate("document.body.classList.contains('menu-open')")


def test_paid_toggle_without_reload(phone, base_url):
    browser, device = phone
    page = browser.new_context(**device).new_page()
    login(page, base_url)
    page.goto(base_url + "/reports?year=2026&month=11")
    url = page.url
    toggle = page.locator(".paid-toggle").first
    was_paid = "is-paid" in (toggle.get_attribute("class") or "")
    toggle.locator("button").tap()
    page.wait_for_timeout(800)
    assert page.url == url
    assert ("is-paid" in (toggle.get_attribute("class") or "")) is not was_paid
    toggle.locator("button").tap()  # trả lại như cũ
    page.wait_for_timeout(800)


def test_tenant_portal_on_phone(phone, base_url):
    browser, device = phone
    tenant = q.tenant_list()[0]
    if not tenant.PortalToken:
        from src.portal import new_token

        q.set_tenant_portal_token(tenant.TenantId, new_token())
    token = q.tenant_portal_token(tenant.TenantId)
    page = browser.new_context(**device).new_page()
    page.goto(f"{base_url}/k/{token}")
    assert page.locator("h1").inner_text().startswith("Chào")
    assert no_overflow(page)


def test_tenant_reports_payment_on_phone(phone, base_url):
    browser, device = phone
    tenant = q.tenant_list()[1]
    if not tenant.PortalToken:
        from src.portal import new_token

        q.set_tenant_portal_token(tenant.TenantId, new_token())
    token = q.tenant_portal_token(tenant.TenantId)
    bill = q.tenant_bills(q.tenant_by_portal_token(token))[0]
    q.set_bill_paid(bill.RoomMonthlyBillId, False)
    page = browser.new_context(**device).new_page()
    page.goto(f"{base_url}/k/{token}/hoa-don/{bill.RoomMonthlyBillId}")
    if page.locator("text=Tôi đã chuyển khoản").count():
        page.locator("text=Tôi đã chuyển khoản").tap()
        page.wait_for_load_state("networkidle")
    assert "chờ chủ nhà xác nhận" in page.content()
    assert q.get_bill(bill.RoomMonthlyBillId).TenantReportedPaidAt is not None


def test_motion_respects_reduced_motion(phone, base_url):
    """Bình thường số tiền đếm tăng dần; máy bật "Giảm chuyển động" thì hiện ngay số cuối, không hiệu ứng."""
    browser, device = phone
    page = browser.new_context(**device).new_page()
    login(page, base_url)
    final = page.locator(".stat-value").first.get_attribute("aria-label")
    assert final and any(ch.isdigit() for ch in final)
    page.wait_for_timeout(1200)
    assert page.locator(".stat-value").first.inner_text().replace("\n", " ").startswith(final.split(" ")[0])

    calm = browser.new_context(**device, reduced_motion="reduce").new_page()
    login(calm, base_url)
    value = calm.locator(".stat-value").first
    assert value.get_attribute("aria-label") is None  # motion.js không chạy đếm
    assert calm.evaluate("getComputedStyle(document.querySelector('.stats > *')).animationName") == "none"


def test_theme_picker_and_auto_dark(phone, base_url):
    """Chọn giao diện trong menu, nhớ sau khi tải lại; "Tự động" theo chế độ tối của điện thoại."""
    browser, device = phone
    page = browser.new_context(**device, color_scheme="light").new_page()
    login(page, base_url)
    attrs = "[document.documentElement.dataset.theme, document.documentElement.hasAttribute('data-glass')]"
    assert page.evaluate(attrs) == ["light", False]
    page.locator("[data-menu-toggle]").tap()
    page.locator('[data-theme-set="dark"]').tap()
    page.wait_for_timeout(500)
    assert page.evaluate(attrs) == ["dark", True]
    assert page.locator('[data-theme-set="dark"]').get_attribute("aria-checked") == "true"
    page.reload()
    assert page.evaluate(attrs) == ["dark", True]
    page.locator("[data-menu-toggle]").tap()
    page.locator('[data-theme-set="glass"]').tap()
    page.wait_for_timeout(500)
    assert page.evaluate(attrs) == ["light", True]
    assert no_overflow(page)

    auto = browser.new_context(**device, color_scheme="dark").new_page()
    login(auto, base_url)
    assert auto.evaluate(attrs) == ["dark", True]  # chưa chọn gì => theo điện thoại
    assert auto.evaluate("document.querySelector('meta[name=theme-color]').content") == "#171412"
