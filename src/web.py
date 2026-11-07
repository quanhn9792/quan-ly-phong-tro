from __future__ import annotations

import gzip
import os
import secrets
from datetime import date
from decimal import Decimal
from io import BytesIO
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

import pyodbc
from flask import Flask, abort, flash, g, redirect, render_template, request, send_file, send_from_directory, session, url_for
from werkzeug.middleware.proxy_fix import ProxyFix

from . import queries as q
from .auth import register_auth
from .portal import new_token, register_portal
from .db import PROJECT_ROOT, init_database
from .formatting import format_date, format_money, format_number, money_input, parse_decimal
from .notify import (
    bill_image_filename,
    bill_notice_image_bytes,
    bill_notice_thumb_bytes,
    bill_payment_qr_bytes,
    binary_value,
    email_settings_ready,
    has_uploaded_qr,
    payment_memo,
    send_bill_email,
    send_test_email,
    unit_title,
    zalo_link,
    zalo_phone,
)

STATUS_LABELS = dict(q.RENTAL_STATUSES)
ALLOWED_QR_IMAGE_MIME_TYPES = {"image/png", "image/jpeg", "image/webp"}
FIELD_LABELS = {
    "year": "Năm",
    "month": "Tháng",
    "rent_amount": "Tiền thuê",
    "service_fee": "Phí dịch vụ",
    "laundry_fee": "Phí máy giặt chung",
    "electricity_unit_price": "Đơn giá điện",
    "water_unit_price": "Đơn giá nước",
    "effective_from_month": "Tháng bắt đầu áp dụng",
    "effective_from_year": "Năm bắt đầu áp dụng",
    "effective_to_month": "Tháng kết thúc áp dụng",
    "effective_to_year": "Năm kết thúc áp dụng",
    "electricity_price": "Đơn giá điện",
    "water_price": "Đơn giá nước",
    "electric_old": "Chỉ số điện cũ",
    "electric_new": "Chỉ số điện mới",
    "water_old": "Chỉ số nước cũ",
    "water_new": "Chỉ số nước mới",
    "room_id": "Phòng",
    "property_id": "Nhà",
    "property_name": "Tên nhà",
    "property_type": "Loại hình",
    "room_code": "Mã phòng/căn",
    "full_name": "Họ tên khách thuê",
    "rental_status": "Trạng thái thuê",
    "smtp_port": "SMTP port",
}


# ----- Đọc form -----

def form_text(name: str, required: bool = False, max_length: int | None = None) -> str | None:
    value = request.form.get(name, "").strip()
    if required and not value:
        raise ValueError(f"{FIELD_LABELS.get(name, name)} không được để trống.")
    return (value[:max_length] if max_length else value) or None


def form_decimal(name: str, default: Decimal | None = None) -> Decimal:
    raw = request.form.get(name, "").strip()
    if not raw and default is not None:
        return default
    try:
        value = parse_decimal(raw)
    except ValueError as exc:
        raise ValueError(f"{FIELD_LABELS.get(name, name)} không hợp lệ.") from exc
    if value < 0:
        raise ValueError(f"{FIELD_LABELS.get(name, name)} không được âm.")
    return value


def form_optional_decimal(name: str) -> Decimal | None:
    return form_decimal(name) if request.form.get(name, "").strip() else None


def form_int(name: str, min_value: int | None = None, max_value: int | None = None) -> int:
    label = FIELD_LABELS.get(name, name)
    try:
        value = int(request.form.get(name, "").strip())
    except ValueError as exc:
        raise ValueError(f"{label} không hợp lệ.") from exc
    if (min_value is not None and value < min_value) or (max_value is not None and value > max_value):
        raise ValueError(f"{label} phải trong khoảng {min_value}–{max_value}.")
    return value


def form_optional_int(name: str, min_value: int | None = None, max_value: int | None = None) -> int | None:
    return form_int(name, min_value, max_value) if request.form.get(name, "").strip() else None


def form_choice(name: str, choices: dict[str, str]) -> str:
    value = request.form.get(name, "").strip().upper()
    if value not in choices:
        raise ValueError(f"{FIELD_LABELS.get(name, name)} không hợp lệ.")
    return value


def year_month_from_args() -> tuple[int, int]:
    today = date.today()

    def parse(name: str, default: int, low: int, high: int) -> int:
        try:
            return min(max(int(request.values.get(name, default)), low), high)
        except ValueError:
            return default

    return parse("year", today.year, 2000, 2100), parse("month", today.month, 1, 12)


def selected_property_id() -> int | None:
    value = session.get("property_id")
    return int(value) if value else None


def back(default_endpoint: str = "dashboard", **values: Any):
    return redirect(request.referrer or url_for(default_endpoint, **values))


def secret_key() -> str:
    configured = os.getenv("FLASK_SECRET_KEY")
    if configured:
        return configured
    key_file = PROJECT_ROOT / "instance" / "secret_key"
    if not key_file.exists():
        key_file.parent.mkdir(exist_ok=True)
        key_file.write_text(secrets.token_hex(32), encoding="utf-8")
    return key_file.read_text(encoding="utf-8").strip()


def portal_url(token: str) -> str:
    """Link gửi khách. Ưu tiên PUBLIC_URL (địa chỉ tunnel) vì chủ nhà có thể đang mở web bằng 127.0.0.1."""
    path = url_for("portal_home", token=token)
    public = os.getenv("PUBLIC_URL", "").strip().rstrip("/")
    return public + path if public else request.host_url.rstrip("/") + path


def is_local_host() -> bool:
    host = request.host.split(":")[0]
    return not os.getenv("PUBLIC_URL") and host in {"127.0.0.1", "localhost", "::1", "[::1]"}


COMPRESSIBLE_TYPES = {"text/html", "text/css", "text/plain", "application/javascript", "text/javascript",
                      "application/json", "application/manifest+json", "image/svg+xml"}


def compress_response(response):
    """Nén gzip HTML/CSS/JS: nhỏ đi ~5 lần, đáng kể khi dùng 4G qua tunnel."""
    if (
        response.status_code != 200
        or response.mimetype not in COMPRESSIBLE_TYPES
        or "Content-Encoding" in response.headers
        or "gzip" not in request.headers.get("Accept-Encoding", "").lower()
    ):
        return response
    response.direct_passthrough = False
    data = response.get_data()
    if len(data) < 1024:
        return response
    response.set_data(gzip.compress(data, compresslevel=6))
    response.headers["Content-Encoding"] = "gzip"
    response.headers.add("Vary", "Accept-Encoding")
    if response.headers.get("ETag"):
        etag, weak = response.get_etag()
        if etag:
            response.set_etag(etag, weak=True)
    return response


def create_app() -> Flask:
    app = Flask(__name__, template_folder=str(PROJECT_ROOT / "templates"), static_folder=str(PROJECT_ROOT / "static"))
    app.config["SECRET_KEY"] = secret_key()
    app.config["MAX_CONTENT_LENGTH"] = 6 * 1024 * 1024
    app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 86400  # file tĩnh: cache 1 ngày (đổi ?v= để cập nhật ngay)
    app.config["TEMPLATES_AUTO_RELOAD"] = os.getenv("TEMPLATES_AUTO_RELOAD") == "1"  # tiện khi sửa giao diện
    if os.getenv("TRUST_PROXY") == "1":
        # Chạy sau Tailscale Funnel / Cloudflare Tunnel: lấy đúng IP + https của người dùng
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)  # type: ignore[method-assign]
        app.config["SESSION_COOKIE_SECURE"] = True
    register_auth(app)
    register_portal(app)
    app.after_request(compress_response)

    app.jinja_env.filters.update(
        money=format_money,
        num=format_number,
        money_input=money_input,
        vndate=format_date,
        status=lambda value: STATUS_LABELS.get(value or "", value or ""),
        property_type=lambda value: q.PROPERTY_TYPE_LABELS.get(value or "", value or ""),
        unit_title=unit_title,
        payment_memo=payment_memo,
        zalo_link=zalo_link,
        image_filename=bill_image_filename,
        zalo_phone=zalo_phone,
    )
    app.jinja_env.globals.update(shift_month=q.shift_month, today=date.today, portal_url=portal_url, is_local_host=is_local_host)

    @app.context_processor
    def inject_properties():
        if g.get("user") is None:
            return {"all_properties": [], "current_property": None, "show_property": False}
        try:
            properties = q.property_list()
        except pyodbc.Error:
            properties = []
        current_id = selected_property_id()
        current = next((p for p in properties if p.PropertyId == current_id), None)
        if current_id and current is None:
            session.pop("property_id", None)
        return {
            "all_properties": properties,
            "current_property": current,
            "show_property": current is None and len(properties) > 1,
        }

    @app.errorhandler(pyodbc.Error)
    def handle_db_error(error: pyodbc.Error):
        return render_template("error.html", error=str(error)), 500

    # ----- PWA: cài lên màn hình chính điện thoại -----

    @app.get("/sw.js")
    def service_worker():
        # Service worker phải nằm ở gốc "/" để điều khiển được mọi trang
        response = send_from_directory(app.static_folder, "sw.js", mimetype="application/javascript", max_age=0)
        response.headers["Cache-Control"] = "no-cache"
        return response

    @app.get("/manifest.webmanifest")
    def manifest():
        return send_from_directory(app.static_folder, "manifest.webmanifest", mimetype="application/manifest+json", max_age=3600)

    @app.get("/offline")
    def offline_page():
        return render_template("offline.html")

    @app.post("/select-property")
    def select_property():
        value = request.form.get("property_id", "")
        if value.isdigit():
            session["property_id"] = int(value)
        else:
            session.pop("property_id", None)
        target = request.form.get("next", "")
        return redirect(target) if target.startswith("/") and not target.startswith("//") else back()

    @app.get("/")
    def dashboard():
        year, month = year_month_from_args()
        property_id = selected_property_id()
        bills = q.month_bills(year, month, property_id)
        rooms = q.room_list(property_id)
        return render_template(
            "dashboard.html",
            year=year,
            month=month,
            rooms=rooms,
            rooms_count=len(rooms),
            occupied_count=sum(1 for room in rooms if room.RentalStatus == "OCCUPIED"),
            bills=bills,
            bills_by_room={bill.RoomId: bill for bill in bills},
            total=sum((Decimal(bill.TotalAmount) for bill in bills), Decimal("0")),
            paid_total=sum((Decimal(bill.TotalAmount) for bill in bills if bill.PaidAt), Decimal("0")),
            paid_count=sum(1 for bill in bills if bill.PaidAt),
            overdue=q.unpaid_bills_before(year, month, property_id),
            configured_month=q.get_month(year, month),
        )

    @app.post("/init-db")
    def init_db():
        init_database()
        flash("Đã kiểm tra/cập nhật cấu trúc database.", "success")
        return redirect(url_for("dashboard"))

    # ----- Nhà -----

    @app.route("/properties", methods=["GET", "POST"])
    def properties_page():
        if request.method == "POST":
            try:
                name = form_text("property_name", required=True, max_length=150)
                property_type = form_choice("property_type", q.PROPERTY_TYPE_LABELS)
                address = form_text("address", max_length=255)
                note = form_text("note", max_length=500)
                rent_amount = form_optional_decimal("rent_amount")
            except ValueError as exc:
                flash(str(exc), "error")
                return redirect(url_for("properties_page"))

            property_id = q.save_property(None, name, property_type, address, note)
            if property_type in {"WHOLE_HOUSE", "APARTMENT"}:
                q.create_room(
                    property_id, "Nguyên căn", name[:100], rent_amount or Decimal("0"), Decimal("0"), Decimal("0"),
                    Decimal("4000"), Decimal("25000"),
                )
                flash(f"Đã thêm “{name}” kèm 1 căn cho thuê nguyên căn. Chỉnh giá điện nước ở trang Phòng & căn.", "success")
            else:
                flash(f"Đã thêm “{name}”. Tiếp theo: thêm các phòng ở trang Phòng & căn.", "success")
            session["property_id"] = property_id
            return redirect(url_for("rooms_page"))

        return render_template(
            "properties.html",
            properties=q.property_list(include_inactive=True),
            property_types=q.PROPERTY_TYPES,
        )

    @app.post("/properties/<int:property_id>")
    def update_property(property_id: int):
        if q.get_property(property_id) is None:
            abort(404)
        try:
            name = form_text("property_name", required=True, max_length=150)
            property_type = form_choice("property_type", q.PROPERTY_TYPE_LABELS)
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for("properties_page"))
        is_active = request.form.get("is_active", "1") == "1"
        q.save_property(property_id, name, property_type, form_text("address", max_length=255), form_text("note", max_length=500), is_active)
        flash(f"Đã cập nhật “{name}”.", "success")
        return redirect(url_for("properties_page"))

    # ----- Phòng / căn -----

    @app.route("/rooms", methods=["GET", "POST"])
    def rooms_page():
        if request.method == "POST":
            try:
                room_id = form_int("room_id")
                prices = (
                    form_decimal("rent_amount"),
                    form_decimal("service_fee", Decimal("0")),
                    form_decimal("laundry_fee", Decimal("0")),
                    form_decimal("electricity_unit_price"),
                    form_decimal("water_unit_price"),
                )
                rental_status = form_choice("rental_status", STATUS_LABELS)
                from_month = form_int("effective_from_month", 1, 12)
                from_year = form_int("effective_from_year", 2000, 2100)
                to_month = form_optional_int("effective_to_month", 1, 12)
                to_year = form_optional_int("effective_to_year", 2000, 2100)
                if (to_month is None) != (to_year is None):
                    raise ValueError("Nếu nhập thời gian kết thúc áp dụng thì cần nhập đủ tháng và năm.")
                if to_month and to_year and q.month_index(to_year, to_month) < q.month_index(from_year, from_month):
                    raise ValueError("Thời gian kết thúc áp dụng phải sau hoặc bằng thời gian bắt đầu.")
            except ValueError as exc:
                flash(str(exc), "error")
                return redirect(url_for("rooms_page"))

            updated = q.update_room_prices(room_id, *prices, rental_status, from_year, from_month, to_year, to_month)
            message = "Đã cập nhật giá và giai đoạn đơn giá."
            if updated:
                until = f"đến {to_month:02d}/{to_year}" if to_month and to_year else "trở đi"
                message += f" Đã tính lại {updated} hóa đơn từ {from_month:02d}/{from_year} {until}."
            flash(message, "success")
            return redirect(url_for("rooms_page"))

        today = date.today()
        property_id = selected_property_id()
        return render_template(
            "rooms.html",
            rooms=q.room_list(property_id),
            rental_statuses=q.RENTAL_STATUSES,
            price_periods_by_room=q.room_price_periods_by_room(),
            current_year=today.year,
            current_month=today.month,
        )

    @app.post("/rooms/new")
    def create_room():
        try:
            property_id = form_int("property_id")
            if q.get_property(property_id) is None:
                raise ValueError("Nhà không tồn tại.")
            room_code = form_text("room_code", required=True, max_length=20)
            room_name = form_text("room_name", max_length=100) or f"Phòng {room_code}"
            q.create_room(
                property_id,
                room_code,
                room_name,
                form_decimal("rent_amount"),
                form_decimal("service_fee", Decimal("0")),
                form_decimal("laundry_fee", Decimal("0")),
                form_decimal("electricity_unit_price"),
                form_decimal("water_unit_price"),
            )
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for("rooms_page"))
        except pyodbc.IntegrityError:
            flash(f"Mã “{room_code}” đã có trong nhà này.", "error")
            return redirect(url_for("rooms_page"))
        flash(f"Đã thêm {room_name}.", "success")
        return redirect(url_for("rooms_page"))

    @app.post("/rooms/<int:room_id>/info")
    def update_room_info(room_id: int):
        room = q.get_room(room_id)
        if room is None:
            abort(404)
        if request.form.get("action") == "deactivate":
            if room.CurrentTenantCount:
                flash(f"{room.RoomCode} còn khách đang thuê — hãy kết thúc thuê trước khi ngừng quản lý.", "error")
            else:
                q.deactivate_room(room_id)
                flash(f"Đã ngừng quản lý {room.RoomCode}. Hóa đơn cũ vẫn được giữ trong báo cáo.", "success")
            return redirect(url_for("rooms_page"))
        try:
            room_code = form_text("room_code", required=True, max_length=20)
            q.update_room_info(
                room_id,
                form_int("property_id"),
                room_code,
                form_text("room_name", max_length=100) or f"Phòng {room_code}",
            )
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for("rooms_page"))
        except pyodbc.IntegrityError:
            flash(f"Mã “{room_code}” đã có trong nhà đó.", "error")
            return redirect(url_for("rooms_page"))
        flash("Đã cập nhật thông tin phòng.", "success")
        return redirect(url_for("rooms_page"))

    # ----- Khách thuê -----

    def tenant_fields_from_form(is_new: bool, room: Any) -> dict[str, Any]:
        fields: dict[str, Any] = {
            "RoomId": room.RoomId,
            "FullName": form_text("full_name", required=True, max_length=120),
            "Phone": form_text("phone", max_length=30),
            "Email": form_text("email", max_length=255),
            "ZaloPhone": form_text("zalo_phone", max_length=30),
            "ZaloUserId": form_text("zalo_user_id", max_length=100),
            "CitizenId": form_text("citizen_id", max_length=30),
            "PermanentAddress": form_text("permanent_address", max_length=255),
            "MoveInDate": form_text("move_in_date"),
            "Note": form_text("note", max_length=500),
            "RentAmount": form_decimal("rent_amount", Decimal(room.RentAmount) if is_new else None),
            "ServiceFee": form_decimal("service_fee", Decimal(room.DefaultServiceFee) if is_new else None),
        }
        if is_new:
            fields["IsCurrent"] = 1
        else:
            is_current = request.form.get("is_current") == "1"
            fields["IsCurrent"] = 1 if is_current else 0
            fields["MoveOutDate"] = form_text("move_out_date") or (None if is_current else date.today().isoformat())
        return fields

    @app.route("/tenants", methods=["GET", "POST"])
    def tenants_page():
        if request.method == "POST":
            try:
                room = q.get_room(form_int("room_id"))
                if room is None:
                    raise ValueError("Không tìm thấy phòng.")
                q.save_tenant(None, tenant_fields_from_form(True, room))
            except ValueError as exc:
                flash(str(exc), "error")
                return redirect(url_for("tenants_page"))
            q.sync_room_status(room.RoomId)
            flash("Đã thêm khách thuê.", "success")
            return redirect(url_for("tenants_page"))

        property_id = selected_property_id()
        return render_template("tenants.html", rooms=q.room_list(property_id), tenants=q.tenant_list(property_id))

    @app.post("/tenants/<int:tenant_id>")
    def update_tenant(tenant_id: int):
        existing = q.one("SELECT RoomId FROM dbo.Tenants WHERE TenantId = ?;", (tenant_id,))
        if existing is None:
            flash("Không tìm thấy khách thuê.", "error")
            return redirect(url_for("tenants_page"))
        try:
            room = q.get_room(form_int("room_id"))
            if room is None:
                raise ValueError("Không tìm thấy phòng.")
            q.save_tenant(tenant_id, tenant_fields_from_form(False, room))
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for("tenants_page"))
        for room_id in {existing.RoomId, room.RoomId}:
            q.sync_room_status(room_id)
        flash("Đã cập nhật khách thuê.", "success")
        return redirect(url_for("tenants_page"))

    @app.post("/tenants/<int:tenant_id>/end")
    def end_tenant(tenant_id: int):
        tenant = q.one("SELECT RoomId FROM dbo.Tenants WHERE TenantId = ?;", (tenant_id,))
        if tenant is None:
            flash("Không tìm thấy khách thuê.", "error")
            return redirect(url_for("tenants_page"))
        q.end_tenancy(tenant_id)
        q.sync_room_status(tenant.RoomId)
        flash("Đã chuyển khách thuê sang trạng thái đã ngưng thuê.", "success")
        return redirect(url_for("tenants_page"))

    @app.post("/tenants/<int:tenant_id>/portal-link")
    def tenant_portal_link(tenant_id: int):
        if q.one("SELECT 1 AS Found FROM dbo.Tenants WHERE TenantId = ?;", (tenant_id,)) is None:
            abort(404)
        if request.form.get("action") == "revoke":
            q.set_tenant_portal_token(tenant_id, None)
            flash("Đã thu hồi link của khách. Link cũ không còn mở được.", "success")
        else:
            q.set_tenant_portal_token(tenant_id, new_token())
            flash("Đã tạo link mới cho khách. Bấm \"Copy link\" rồi gửi qua Zalo.", "success")
        return redirect(url_for("tenants_page") + f"#tenant-{tenant_id}")

    # ----- Đơn giá tháng -----

    @app.route("/months", methods=["GET", "POST"])
    def months_page():
        year, month = year_month_from_args()
        if request.method == "POST":
            try:
                q.save_month(year, month, form_decimal("electricity_price"), form_decimal("water_price"), form_decimal("service_fee"))
            except ValueError as exc:
                flash(str(exc), "error")
            else:
                flash(f"Đã lưu đơn giá tháng {month:02d}/{year}.", "success")
            return redirect(url_for("months_page", year=year, month=month))

        return render_template(
            "months.html",
            year=year,
            month=month,
            month_data=q.get_month(year, month),
            default_electricity=q.DEFAULT_ELECTRICITY_PRICE,
            default_water=q.DEFAULT_WATER_PRICE,
            default_service=q.DEFAULT_SERVICE_FEE,
        )

    # ----- Nhập hóa đơn -----

    @app.route("/bills/new", methods=["GET", "POST"])
    def bill_form():
        year, month = year_month_from_args()
        property_id = selected_property_id()
        room_id_raw = request.values.get("room_id", "")
        room = q.get_room(int(room_id_raw)) if room_id_raw.isdigit() else None

        if request.method == "POST":
            if room is None:
                flash("Không tìm thấy phòng.", "error")
                return redirect(url_for("bill_form", year=year, month=month))
            try:
                electric_new = form_decimal("electric_new")
                water_new = form_decimal("water_new")
                electric_old = form_optional_decimal("electric_old")
                water_old = form_optional_decimal("water_old")
            except ValueError as exc:
                flash(str(exc), "error")
                return redirect(url_for("bill_form", year=year, month=month, room_id=room.RoomId))

            prev = q.previous_reading(room.RoomId, year, month)
            electric_old = electric_old if electric_old is not None else Decimal(prev.ElectricNew if prev else 0)
            water_old = water_old if water_old is not None else Decimal(prev.WaterNew if prev else 0)
            if electric_new < electric_old or water_new < water_old:
                flash("Chỉ số mới phải lớn hơn hoặc bằng chỉ số cũ.", "error")
                return redirect(url_for("bill_form", year=year, month=month, room_id=room.RoomId))

            q.save_bill(room, year, month, electric_old, electric_new, water_old, water_new, form_text("note", max_length=500))
            next_room = q.next_unbilled_room(year, month, room.RoomId, property_id)
            if next_room is not None:
                flash(f"Đã lưu hóa đơn {room.RoomCode}. Tiếp theo: {next_room.RoomCode}.", "success")
                return redirect(url_for("bill_form", year=year, month=month, room_id=next_room.RoomId))
            flash(f"Đã lưu hóa đơn {room.RoomCode}. Đã nhập đủ tất cả phòng tháng {month:02d}/{year}.", "success")
            return redirect(url_for("reports_page", year=year, month=month))

        month_data = q.get_month(year, month)
        charge_rent, charge_service, charge_laundry, charge_electricity_price, charge_water_price = q.room_prices_for_month(
            room, year, month, month_data
        )
        return render_template(
            "bill_form.html",
            rooms=q.room_list(property_id),
            billed_room_ids=q.billed_room_ids(year, month),
            existing_bill=q.bill_for_room_month(room.RoomId, year, month) if room else None,
            selected_room=room,
            year=year,
            month=month,
            month_data=month_data,
            prev=q.previous_reading(room.RoomId, year, month) if room else None,
            selected_contract=q.tenant_contract(room.RoomId, year, month) if room else None,
            charge_rent=charge_rent,
            charge_service=charge_service,
            charge_laundry=charge_laundry,
            charge_electricity_price=charge_electricity_price,
            charge_water_price=charge_water_price,
        )

    # ----- Báo cáo & gửi khách -----

    @app.get("/reports")
    def reports_page():
        today = date.today()
        try:
            year = int(request.args.get("year", today.year))
        except ValueError:
            year = today.year
        raw_month = request.args.get("month")
        if raw_month and raw_month.isdigit() and 1 <= int(raw_month) <= 12:
            month: int | None = int(raw_month)
        else:
            month = today.month if raw_month is None and year == today.year else None

        property_id = selected_property_id()
        month_summaries = q.report_month_summaries(year, property_id)
        bills = q.month_bills(year, month, property_id) if month else []
        return render_template(
            "reports.html",
            year=year,
            month=month,
            month_summaries=month_summaries,
            year_total=sum((Decimal(item.TotalAmount) for item in month_summaries), Decimal("0")),
            bills=bills,
            total=sum((Decimal(bill.TotalAmount) for bill in bills), Decimal("0")),
            paid_total=sum((Decimal(bill.TotalAmount) for bill in bills if bill.PaidAt), Decimal("0")),
        )

    def bill_or_404(bill_id: int) -> Any:
        bill = q.get_bill(bill_id)
        if bill is None:
            abort(404)
        return bill

    @app.get("/reports/bills/<int:bill_id>")
    def bill_detail_page(bill_id: int):
        settings = q.payment_settings()
        return render_template(
            "bill_detail.html",
            bill=bill_or_404(bill_id),
            payment_settings=settings,
            has_payment_qr=has_uploaded_qr(settings),
        )

    @app.get("/reports/bills/<int:bill_id>/qr.png")
    def bill_payment_qr(bill_id: int):
        data = bill_payment_qr_bytes(bill_or_404(bill_id), q.payment_settings())
        return send_file(BytesIO(data), mimetype="image/png", max_age=0)

    @app.get("/reports/bills/<int:bill_id>/thumb.jpg")
    def bill_notice_thumb(bill_id: int):
        data = bill_notice_thumb_bytes(bill_or_404(bill_id), q.payment_settings())
        return send_file(BytesIO(data), mimetype="image/jpeg", max_age=0)

    @app.get("/reports/bills/<int:bill_id>/notice.png")
    def bill_notice_image(bill_id: int):
        bill = bill_or_404(bill_id)
        data = bill_notice_image_bytes(bill, q.payment_settings())
        return send_file(BytesIO(data), mimetype="image/png", download_name=bill_image_filename(bill), max_age=0)

    def deliver_email(bill: Any, settings: Any) -> tuple[bool, str]:
        recipient = (bill.TenantEmail or "").strip()
        if not recipient:
            q.log_bill_delivery(int(bill.RoomMonthlyBillId), "EMAIL", None, "FAILED", "Khach thue chua co email")
            return False, f"{bill.RoomCode} chưa có email khách thuê."
        try:
            send_bill_email(bill, recipient, settings)
        except Exception as exc:  # lỗi SMTP/mạng: ghi log và báo lại cho người dùng
            q.log_bill_delivery(int(bill.RoomMonthlyBillId), "EMAIL", recipient, "FAILED", str(exc))
            return False, f"Gửi email {bill.RoomCode} lỗi: {exc}"
        q.log_bill_delivery(int(bill.RoomMonthlyBillId), "EMAIL", recipient, "SENT")
        return True, f"Đã gửi email {bill.RoomCode}: {recipient}."

    def smtp_settings_or_none() -> Any | None:
        settings = q.payment_settings()
        if not email_settings_ready(settings):
            flash("Chưa cấu hình SMTP để gửi email. Hãy nhập thông tin ở Cài đặt › QR & email.", "error")
            return None
        return settings

    @app.post("/reports/bills/<int:bill_id>/send-email")
    def send_bill_email_page(bill_id: int):
        bill = bill_or_404(bill_id)
        settings = smtp_settings_or_none()
        if settings is None:
            return redirect(url_for("payment_settings_page"))
        ok, message = deliver_email(bill, settings)
        flash(message, "success" if ok else "error")
        return redirect(url_for("bill_detail_page", bill_id=bill_id))

    @app.post("/reports/send-month-email")
    def send_month_email():
        try:
            year, month = form_int("year", 2000, 2100), form_int("month", 1, 12)
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for("reports_page"))
        settings = smtp_settings_or_none()
        if settings is None:
            return redirect(url_for("payment_settings_page"))

        results = [deliver_email(bill, settings) for bill in q.month_bills(year, month, selected_property_id())]
        sent = sum(1 for ok, _ in results if ok)
        failed = len(results) - sent
        flash(f"Gửi email tháng {month:02d}/{year}: thành công {sent}, không gửi được {failed}.", "success" if not failed else "error")
        return redirect(url_for("reports_page", year=year, month=month))

    @app.get("/reports/zalo")
    def zalo_queue_page():
        year, month = year_month_from_args()
        bills = q.month_bills(year, month, selected_property_id())
        sent_ids = {
            int(item.RoomMonthlyBillId)
            for item in q.rows(
                """
                SELECT DISTINCT l.RoomMonthlyBillId
                FROM dbo.BillDeliveryLogs AS l
                INNER JOIN dbo.v_MonthlyRoomBills AS b ON b.RoomMonthlyBillId = l.RoomMonthlyBillId
                WHERE l.Channel = N'ZALO' AND l.Status = N'SENT' AND b.YearNumber = ? AND b.MonthNumber = ?;
                """,
                (year, month),
            )
        }
        return render_template("zalo_send.html", year=year, month=month, bills=bills, sent_ids=sent_ids)

    @app.post("/reports/bills/<int:bill_id>/paid")
    def set_bill_paid(bill_id: int):
        bill = bill_or_404(bill_id)
        paid = request.form.get("paid") == "1"
        q.set_bill_paid(bill_id, paid)
        if request.headers.get("X-Requested-With") == "fetch":
            return {"paid": paid}
        flash(f"{bill.RoomCode} tháng {bill.MonthNumber:02d}/{bill.YearNumber}: {'đã thu tiền' if paid else 'chuyển về chưa thu'}.", "success")
        return back("bill_detail_page", bill_id=bill_id)

    @app.post("/reports/bills/<int:bill_id>/zalo-sent")
    def log_zalo_sent(bill_id: int):
        bill = bill_or_404(bill_id)
        q.log_bill_delivery(bill_id, "ZALO", zalo_phone(bill), "SENT")
        return "", 204

    @app.post("/reports/export-month-images")
    def export_month_images():
        try:
            year, month = form_int("year", 2000, 2100), form_int("month", 1, 12)
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for("reports_page"))
        bills = q.month_bills(year, month, selected_property_id())
        if not bills:
            flash("Tháng này chưa có hóa đơn để xuất ảnh.", "error")
            return redirect(url_for("reports_page", year=year, month=month))

        settings = q.payment_settings()
        buffer = BytesIO()
        with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
            for bill in bills:
                archive.writestr(bill_image_filename(bill), bill_notice_image_bytes(bill, settings))
                q.log_bill_delivery(int(bill.RoomMonthlyBillId), "EXPORT", None, "EXPORTED")
        buffer.seek(0)
        return send_file(buffer, mimetype="application/zip", as_attachment=True, download_name=f"anh-gui-khach-{year}-{month:02d}.zip", max_age=0)

    # ----- Cài đặt QR & email -----

    @app.route("/payment-settings", methods=["GET", "POST"])
    def payment_settings_page():
        settings = q.payment_settings()
        if request.method == "GET":
            return render_template("payment_settings.html", payment_settings=settings, has_payment_qr=has_uploaded_qr(settings))

        settings_type = request.form.get("settings_type", "qr")
        if settings_type == "test_email":
            if not email_settings_ready(settings):
                flash("Chưa cấu hình đủ SMTP để gửi email test.", "error")
            else:
                recipient = form_text("test_email") or settings.FromEmail or settings.SmtpUsername
                try:
                    send_test_email(recipient, settings)
                    flash(f"Đã gửi email test tới {recipient}. Hãy kiểm tra hộp thư đến hoặc Spam.", "success")
                except Exception as exc:
                    flash(f"Gửi email test lỗi: {exc}", "error")
            return redirect(url_for("payment_settings_page"))

        if settings_type == "email":
            try:
                port = form_int("smtp_port", 1, 65535)
            except ValueError as exc:
                flash(str(exc), "error")
                return redirect(url_for("payment_settings_page"))
            password = request.form.get("smtp_password", "").strip() or (settings.SmtpPassword if settings else None)
            q.save_email_settings(
                form_text("sender_name") or "Quan ly phong tro",
                form_text("from_email"),
                form_text("smtp_host"),
                port,
                request.form.get("smtp_use_tls") == "1",
                form_text("smtp_username"),
                password,
            )
            flash("Đã cập nhật cấu hình gửi email.", "success")
            return redirect(url_for("payment_settings_page"))

        qr = None
        qr_file = request.files.get("payment_qr_image")
        if qr_file and qr_file.filename:
            data = qr_file.read()
            if qr_file.mimetype not in ALLOWED_QR_IMAGE_MIME_TYPES:
                flash("Chỉ hỗ trợ ảnh QR dạng PNG, JPG/JPEG hoặc WEBP.", "error")
                return redirect(url_for("payment_settings_page"))
            if not data or len(data) > 5 * 1024 * 1024:
                flash("Ảnh QR trống hoặc lớn hơn 5 MB.", "error")
                return redirect(url_for("payment_settings_page"))
            qr = (data, qr_file.mimetype, qr_file.filename[:255])
        q.save_qr_settings(form_text("account_info", max_length=500), qr)
        flash("Đã cập nhật mã QR thanh toán.", "success")
        return redirect(url_for("payment_settings_page"))

    @app.get("/payment-settings/qr.png")
    def payment_settings_qr():
        settings = q.payment_settings()
        if not has_uploaded_qr(settings):
            abort(404)
        return send_file(BytesIO(binary_value(settings.QrImage)), mimetype=settings.QrMimeType or "image/png", max_age=0)

    return app
