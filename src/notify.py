"""Tạo ảnh thông báo thanh toán, mã QR và gửi email cho khách."""
from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr
from io import BytesIO
from typing import Any

import qrcode
from PIL import Image, ImageDraw, ImageFont, ImageOps

from .formatting import ascii_upper, format_money, format_number

SINGLE_UNIT_TYPES = {"WHOLE_HOUSE", "APARTMENT"}


def unit_title(bill: Any) -> str:
    """'Phòng 301' cho nhà trọ, tên nhà/căn hộ cho loại cho thuê nguyên căn."""
    if getattr(bill, "PropertyType", None) in SINGLE_UNIT_TYPES:
        return str(bill.PropertyName)
    return f"Phòng {bill.RoomCode}"


def payment_memo(bill: Any) -> str:
    """Nội dung chuyển khoản không dấu, vd: PHONG 301 T102026."""
    period = f"T{int(bill.MonthNumber):02d}{int(bill.YearNumber)}"
    if getattr(bill, "PropertyType", None) in SINGLE_UNIT_TYPES:
        return f"TT {ascii_upper(str(bill.PropertyName))[:20]} {period}"
    return f"PHONG {ascii_upper(str(bill.RoomCode))} {period}"


def zalo_phone(bill: Any) -> str | None:
    """Số Zalo của khách trong tháng hóa đơn (ưu tiên ô Zalo, sau đó số điện thoại), dạng 0xxxxxxxxx."""
    for raw in (getattr(bill, "TenantZaloPhone", None), getattr(bill, "TenantPhone", None)):
        digits = "".join(ch for ch in str(raw or "") if ch.isdigit())
        if digits.startswith("84") and len(digits) == 11:
            digits = "0" + digits[2:]
        if len(digits) >= 9:
            return digits
    return None


def zalo_link(bill: Any) -> str | None:
    """Link mở khung chat Zalo (app Zalo PC/điện thoại hoặc Zalo web) với số của khách."""
    phone = zalo_phone(bill)
    return f"https://zalo.me/{phone}" if phone else None


def bill_image_filename(bill: Any) -> str:
    return f"{ascii_upper(unit_title(bill)).lower()}-{int(bill.YearNumber)}-{int(bill.MonthNumber):02d}.png"


def has_uploaded_qr(settings: Any | None) -> bool:
    return bool(settings and settings.QrImage is not None)


def binary_value(value: Any) -> bytes:
    return value.tobytes() if isinstance(value, memoryview) else bytes(value)


def bill_payment_qr_bytes(bill: Any, settings: Any | None) -> bytes:
    if has_uploaded_qr(settings):
        return binary_value(settings.QrImage)

    content = (bill.PaymentQrContent or "").strip() or "\n".join(
        [
            f"{ascii_upper(unit_title(bill))} {int(bill.MonthNumber):02d}/{int(bill.YearNumber)}",
            f"So tien: {format_money(bill.TotalAmount)}",
            f"Noi dung: {payment_memo(bill)}",
        ]
    )
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=9, border=3)
    qr.add_data(content)
    qr.make(fit=True)
    buffer = BytesIO()
    qr.make_image(fill_color="black", back_color="white").save(buffer, format="PNG")
    return buffer.getvalue()


def _font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    for name in (("arialbd.ttf", "segoeuib.ttf") if bold else ("arial.ttf", "segoeui.ttf")):
        try:
            return ImageFont.truetype(rf"C:\Windows\Fonts\{name}", size=size)
        except OSError:
            pass
    return ImageFont.load_default()


def _text_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> int:
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0]


def bill_notice_image_bytes(bill: Any, settings: Any | None) -> bytes:
    width, height = 1080, 1520
    image = Image.new("RGB", (width, height), "#f4f6f8")
    draw = ImageDraw.Draw(image)

    def right(x: int, y: int, text: str, font: ImageFont.ImageFont, fill: str) -> None:
        draw.text((x - _text_width(draw, text, font), y), text, font=font, fill=fill)

    def center(y: int, text: str, font: ImageFont.ImageFont, fill: str) -> None:
        draw.text((width // 2 - _text_width(draw, text, font) // 2, y), text, font=font, fill=fill)

    draw.rounded_rectangle((54, 54, width - 54, height - 54), radius=18, fill="#ffffff", outline="#d9e0e7", width=2)
    draw.rounded_rectangle((54, 54, width - 54, 200), radius=18, fill="#0f766e")
    draw.rectangle((54, 160, width - 54, 200), fill="#0f766e")

    title_font, subtitle_font = _font(38, bold=True), _font(24)
    label_font, value_font = _font(24, bold=True), _font(28, bold=True)
    small_font, total_font = _font(20), _font(42, bold=True)

    header = "THANH TOÁN TIỀN THUÊ"
    if getattr(bill, "PropertyType", None) not in SINGLE_UNIT_TYPES and getattr(bill, "PropertyName", None):
        header += f" · {str(bill.PropertyName).upper()}"
    draw.text((92, 86), header[:60], font=small_font, fill="#d9fff1")
    draw.text((92, 122), unit_title(bill)[:28], font=title_font, fill="#ffffff")
    right(width - 92, 124, f"{int(bill.MonthNumber):02d}/{int(bill.YearNumber)}", title_font, "#ffffff")

    draw.text((92, 232), "Khách thuê", font=small_font, fill="#66727e")
    draw.text((92, 262), bill.TenantNames or "Chưa nhập khách thuê", font=subtitle_font, fill="#172027")

    lines = [
        ("Tiền thuê", format_money(bill.RentAmount)),
        ("Phí dịch vụ", format_money(bill.ServiceFee)),
        ("Phí máy giặt chung", format_money(bill.LaundryFee)),
        (f"Điện {format_number(bill.ElectricUsage)} kWh", format_money(bill.ElectricityAmount)),
        (f"Nước {format_number(bill.WaterUsage)} m³", format_money(bill.WaterAmount)),
    ]
    y = 340
    for label, value in lines:
        draw.line((92, y - 22, width - 92, y - 22), fill="#d9e0e7", width=2)
        draw.text((92, y), label, font=label_font, fill="#172027")
        right(width - 92, y, value, value_font, "#172027")
        y += 82

    draw.rounded_rectangle((92, y + 10, width - 92, y + 122), radius=14, fill="#e6f4f2")
    draw.text((120, y + 38), "Tổng thanh toán", font=label_font, fill="#0f766e")
    right(width - 120, y + 28, format_money(bill.TotalAmount), total_font, "#0f766e")

    try:
        qr_image = Image.open(BytesIO(bill_payment_qr_bytes(bill, settings))).convert("RGB")
    except Exception:
        qr_image = Image.new("RGB", (360, 360), "white")
    qr_image = ImageOps.contain(qr_image, (380, 380), method=Image.Resampling.LANCZOS)
    qr_top = y + 190
    draw.rounded_rectangle((width // 2 - 245, qr_top, width // 2 + 245, qr_top + 520), radius=18, fill="#fbfcfd", outline="#d9e0e7", width=2)
    image.paste(qr_image, (width // 2 - qr_image.width // 2, qr_top + 30))

    if settings and settings.AccountInfo:
        center(qr_top + 425, str(settings.AccountInfo)[:90], small_font, "#66727e")
    center(qr_top + 460, f"ND: {payment_memo(bill)}", label_font, "#172027")

    buffer = BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def email_settings_ready(settings: Any | None) -> bool:
    return bool(
        settings
        and (settings.SmtpHost or "").strip()
        and settings.SmtpPort
        and (settings.SmtpUsername or "").strip()
        and (settings.SmtpPassword or "").strip()
    )


def send_email(settings: Any, recipient: str, subject: str, body: str, attachment: tuple[str, bytes] | None = None) -> None:
    from_email = (settings.FromEmail or settings.SmtpUsername or "").strip()
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = formataddr(((settings.SenderName or "Quan ly phong tro").strip(), from_email))
    message["To"] = recipient
    message.set_content(body)
    if attachment:
        filename, data = attachment
        message.add_attachment(data, maintype="image", subtype="png", filename=filename)

    host, port = str(settings.SmtpHost).strip(), int(settings.SmtpPort)
    context = ssl.create_default_context()
    if port == 465 and not settings.SmtpUseTls:
        smtp: smtplib.SMTP = smtplib.SMTP_SSL(host, port, timeout=30, context=context)
    else:
        smtp = smtplib.SMTP(host, port, timeout=30)
    with smtp:
        if not isinstance(smtp, smtplib.SMTP_SSL) and settings.SmtpUseTls:
            smtp.starttls(context=context)
        smtp.login(str(settings.SmtpUsername).strip(), str(settings.SmtpPassword))
        smtp.send_message(message)


def send_bill_email(bill: Any, recipient: str, settings: Any) -> None:
    period = f"{int(bill.MonthNumber):02d}/{int(bill.YearNumber)}"
    body = "\n".join(
        [
            "Xin chào,",
            f"Thông tin thanh toán {unit_title(bill)} tháng {period} được đính kèm trong ảnh.",
            f"Tổng thanh toán: {format_money(bill.TotalAmount)}",
            f"Nội dung chuyển khoản: {payment_memo(bill)}",
        ]
    )
    send_email(
        settings,
        recipient,
        f"Thanh toán {unit_title(bill)} tháng {period}",
        body,
        (bill_image_filename(bill), bill_notice_image_bytes(bill, settings)),
    )


def send_test_email(recipient: str, settings: Any) -> None:
    send_email(
        settings,
        recipient,
        "Test gửi email từ Quản lý phòng trọ",
        "Email test gửi thành công. Bạn có thể dùng nút Gửi email ở trang Báo cáo.",
    )
