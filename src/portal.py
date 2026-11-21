"""Cổng khách thuê: mỗi lượt thuê có 1 link bí mật /k/<token>, không cần mật khẩu.

Chủ nhà tạo link ở trang Khách thuê rồi gửi qua Zalo. Khách xem được hóa đơn các tháng mình ở,
QR thanh toán và ảnh hóa đơn; có thể "Thêm vào màn hình chính" như một app riêng.
Thu hồi link => link cũ hết hiệu lực ngay.
"""
from __future__ import annotations

import json
import re
import secrets
from io import BytesIO
from typing import Any

import pyodbc

from flask import Flask, Response, abort, redirect, render_template, request, send_file, url_for

from . import auth
from . import queries as q
from .notify import bill_image_filename, bill_notice_image_bytes, bill_payment_qr_bytes, normalize_phone

TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{32,64}$")
PORTAL_ENDPOINTS = {"portal_home", "portal_bill", "portal_qr", "portal_notice", "portal_manifest", "portal_report_paid"}
# POST từ app của khách: không dùng phiên/CSRF; mã bí mật trong URL đóng vai trò khóa chống giả mạo
CSRF_EXEMPT_ENDPOINTS = {"portal_report_paid"}


def new_token() -> str:
    return secrets.token_urlsafe(32)  # 256 bit, không thể đoán


def tenant_or_404(token: str) -> Any:
    if not TOKEN_PATTERN.match(token):
        abort(404)
    tenant = q.tenant_by_portal_token(token)
    # Khách đã ngưng thuê: link không còn hiệu lực (kể cả link tạo từ trước khi có quy tắc tự thu hồi)
    if tenant is None or not tenant.IsCurrent:
        abort(404)
    return tenant


def only_own_info(bill: Any, tenant: Any) -> Any:
    """Hóa đơn tháng có đổi khách chứa tên/liên hệ của người khác: chỉ để lại tên của chính khách đang xem."""
    bill.TenantNames = tenant.FullName
    for column in ("TenantPhone", "TenantEmail", "TenantZaloPhone", "TenantZaloUserId", "TenantPortalToken"):
        setattr(bill, column, None)
    return bill


def own_bills(tenant: Any) -> list[Any]:
    return [only_own_info(bill, tenant) for bill in q.tenant_bills(tenant)]


def tenant_bill_or_404(token: str, bill_id: int) -> tuple[Any, Any]:
    tenant = tenant_or_404(token)
    bill = next((b for b in own_bills(tenant) if int(b.RoomMonthlyBillId) == bill_id), None)
    if bill is None:
        abort(404)
    return tenant, bill


def no_store(response: Response) -> Response:
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return response


def register_portal(app: Flask) -> None:
    auth.PUBLIC_ENDPOINTS.update(PORTAL_ENDPOINTS)

    @app.context_processor
    def portal_contact():
        if not (request.endpoint or "").startswith("portal_"):
            return {}
        try:
            settings = q.payment_settings()
        except pyodbc.Error:  # DB tắt: vẫn hiện được trang "Hệ thống đang bận"
            return {"owner_phone": None}
        return {"owner_phone": normalize_phone(settings.OwnerPhone) if settings else None}
    auth.CSRF_EXEMPT_ENDPOINTS.update(CSRF_EXEMPT_ENDPOINTS)

    @app.get("/k/<token>")
    def portal_home(token: str):
        tenant = tenant_or_404(token)
        bills = own_bills(tenant)
        unpaid = [b for b in bills if not b.PaidAt]
        html = render_template(
            "portal_home.html",
            token=token,
            tenant=tenant,
            bills=bills,
            latest=bills[0] if bills else None,
            unpaid_total=sum((b.TotalAmount for b in unpaid), 0),
            unpaid_count=len(unpaid),
            payment_settings=q.payment_settings(),
        )
        return no_store(Response(html))

    @app.get("/k/<token>/hoa-don/<int:bill_id>")
    def portal_bill(token: str, bill_id: int):
        tenant, bill = tenant_bill_or_404(token, bill_id)
        html = render_template("portal_bill.html", token=token, tenant=tenant, bill=bill, payment_settings=q.payment_settings())
        return no_store(Response(html))

    @app.post("/k/<token>/hoa-don/<int:bill_id>/da-chuyen")
    def portal_report_paid(token: str, bill_id: int):
        _, bill = tenant_bill_or_404(token, bill_id)
        if not bill.PaidAt:
            q.report_tenant_paid(bill_id)
        return redirect(url_for("portal_bill", token=token, bill_id=bill_id, reported=1))

    @app.get("/k/<token>/hoa-don/<int:bill_id>/qr.png")
    def portal_qr(token: str, bill_id: int):
        _, bill = tenant_bill_or_404(token, bill_id)
        return no_store(send_file(BytesIO(bill_payment_qr_bytes(bill, q.payment_settings())), mimetype="image/png", max_age=0))

    @app.get("/k/<token>/hoa-don/<int:bill_id>/anh.png")
    def portal_notice(token: str, bill_id: int):
        _, bill = tenant_bill_or_404(token, bill_id)
        data = bill_notice_image_bytes(bill, q.payment_settings())
        return no_store(send_file(BytesIO(data), mimetype="image/png", download_name=bill_image_filename(bill), max_age=0))

    @app.get("/k/<token>/manifest.webmanifest")
    def portal_manifest(token: str):
        tenant = tenant_or_404(token)
        home = url_for("portal_home", token=token)
        unit = tenant.PropertyName if tenant.PropertyType in ("WHOLE_HOUSE", "APARTMENT") else f"{tenant.RoomCode} · {tenant.PropertyName}"
        manifest = {
            "name": f"Tiền nhà {unit}",
            "short_name": "Tiền nhà",
            "lang": "vi",
            "id": home,
            "start_url": home,
            "scope": home,
            "display": "standalone",
            "background_color": "#f5f7f6",
            "theme_color": "#0f766e",
            "icons": [
                {"src": "/static/icons/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
                {"src": "/static/icons/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
                {"src": "/static/icons/maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
            ],
        }
        return no_store(Response(json.dumps(manifest, ensure_ascii=False), mimetype="application/manifest+json"))
