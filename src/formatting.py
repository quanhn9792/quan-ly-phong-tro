from __future__ import annotations

import unicodedata
from decimal import Decimal, InvalidOperation
from typing import Any


def parse_decimal(raw: str) -> Decimal:
    """Đọc số kiểu Việt Nam: '5.000.000', '5,000,000', '12,5', '12.5' đều hợp lệ."""
    value = raw.strip().replace(" ", "")
    if not value:
        raise ValueError("Gia tri khong duoc de trong.")

    if "," in value and "." in value:
        if value.rfind(",") > value.rfind("."):
            value = value.replace(".", "").replace(",", ".")
        else:
            value = value.replace(",", "")
    else:
        separator = "," if "," in value else "." if "." in value else None
        if separator:
            parts = value.split(separator)
            is_thousands = len(parts) > 2 or all(len(part) == 3 for part in parts[1:])
            value = "".join(parts) if is_thousands else value.replace(",", ".")

    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"Gia tri khong hop le: {raw}") from exc


def format_money(value: Any) -> str:
    amount = Decimal(value or 0).quantize(Decimal("1"))
    return f"{amount:,.0f} VND".replace(",", ".")


def format_number(value: Any) -> str:
    number = Decimal(value or 0)
    if number == number.to_integral():
        return f"{number:,.0f}".replace(",", ".")
    return f"{number:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def money_input(value: Any) -> str:
    if value is None:
        return ""
    amount = Decimal(value)
    if amount == amount.to_integral():
        return str(amount.quantize(Decimal("1")))
    return str(amount)


def format_date(value: Any) -> str:
    if not value:
        return ""
    if hasattr(value, "strftime"):
        return value.strftime("%d/%m/%Y")
    return str(value)


def ascii_upper(value: str) -> str:
    text = unicodedata.normalize("NFD", value.replace("đ", "d").replace("Đ", "D"))
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return "".join(ch for ch in text.upper() if ch.isalnum())
