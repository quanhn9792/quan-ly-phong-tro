"""Truy vấn database và quy tắc tính giá hóa đơn."""
from __future__ import annotations

from calendar import monthrange
from datetime import date
from decimal import Decimal
from typing import Any

import pyodbc

from .db import connect, execute, one, rows

RENTAL_STATUSES = [
    ("VACANT", "Trống"),
    ("OCCUPIED", "Đang thuê"),
    ("RESERVED", "Đặt cọc"),
    ("MAINTENANCE", "Bảo trì"),
]
PROPERTY_TYPES = [
    ("ROOMING_HOUSE", "Nhà trọ / chung cư mini (cho thuê từng phòng)"),
    ("WHOLE_HOUSE", "Nhà riêng (cho thuê nguyên căn)"),
    ("APARTMENT", "Căn hộ chung cư (cho thuê nguyên căn)"),
    ("OTHER", "Khác (mặt bằng, kho, văn phòng…)"),
]
PROPERTY_TYPE_LABELS = dict(PROPERTY_TYPES)
DEFAULT_ELECTRICITY_PRICE = Decimal("4000")
DEFAULT_WATER_PRICE = Decimal("20000")
DEFAULT_SERVICE_FEE = Decimal("100000")
ZERO = Decimal("0")

BILL_COLUMNS = """
    RoomMonthlyBillId, BillingMonthId, RoomId, YearNumber, MonthNumber,
    PropertyId, PropertyName, PropertyType,
    RoomCode, RoomName, RentalStatus, TenantNames, TenantEmail, TenantPhone, TenantZaloPhone, TenantZaloUserId,
    RentAmount, ServiceFee, LaundryFee,
    ElectricOld, ElectricNew, ElectricUsage, ElectricityUnitPrice, ElectricityAmount,
    WaterOld, WaterNew, WaterUsage, WaterUnitPrice, WaterAmount,
    TotalAmount, Note, PaymentQrContent, CreatedAt, UpdatedAt
"""

PERIOD_COLUMNS = """
    RoomPricePeriodId, RoomId, EffectiveFromYear, EffectiveFromMonth, EffectiveToYear, EffectiveToMonth,
    RentAmount, ServiceFee, LaundryFee, ElectricityUnitPrice, WaterUnitPrice, Note
"""


def property_filter(column: str, property_id: int | None) -> tuple[str, tuple[Any, ...]]:
    return (f"AND {column} = ?", (property_id,)) if property_id else ("", ())


def month_bounds(year: int, month: int) -> tuple[date, date]:
    return date(year, month, 1), date(year, month, monthrange(year, month)[1])


def month_index(year: int, month: int) -> int:
    return year * 12 + month


def shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) + delta
    return index // 12, index % 12 + 1


# ----- Nhà / tòa nhà -----

def property_list(include_inactive: bool = False) -> list[Any]:
    where = "" if include_inactive else "WHERE p.IsActive = 1"
    return rows(
        f"""
        SELECT p.PropertyId, p.PropertyName, p.PropertyType, p.Address, p.Note, p.IsActive,
               COUNT(r.RoomId) AS UnitCount,
               SUM(CASE WHEN r.RentalStatus = N'OCCUPIED' THEN 1 ELSE 0 END) AS OccupiedCount
        FROM dbo.Properties AS p
        LEFT JOIN dbo.Rooms AS r ON r.PropertyId = p.PropertyId AND r.IsActive = 1
        {where}
        GROUP BY p.PropertyId, p.PropertyName, p.PropertyType, p.Address, p.Note, p.IsActive
        ORDER BY p.IsActive DESC, p.PropertyName;
        """
    )


def get_property(property_id: int) -> Any | None:
    return one(
        "SELECT PropertyId, PropertyName, PropertyType, Address, Note, IsActive FROM dbo.Properties WHERE PropertyId = ?;",
        (property_id,),
    )


def save_property(property_id: int | None, name: str, property_type: str, address: str | None, note: str | None, is_active: bool = True) -> int:
    with connect() as cnxn:
        cursor = cnxn.cursor()
        if property_id:
            cursor.execute(
                """
                UPDATE dbo.Properties
                SET PropertyName = ?, PropertyType = ?, Address = ?, Note = ?, IsActive = ?, UpdatedAt = SYSDATETIME()
                WHERE PropertyId = ?;
                """,
                name, property_type, address, note, 1 if is_active else 0, property_id,
            )
        else:
            cursor.execute(
                """
                INSERT INTO dbo.Properties (PropertyName, PropertyType, Address, Note)
                OUTPUT INSERTED.PropertyId
                VALUES (?, ?, ?, ?);
                """,
                name, property_type, address, note,
            )
            property_id = int(cursor.fetchone()[0])
        cnxn.commit()
    return property_id


# ----- Phòng / căn -----

ROOM_SELECT = """
    SELECT
        r.RoomId, r.PropertyId, p.PropertyName, p.PropertyType,
        r.RoomCode, r.RoomName, r.RentAmount, r.DefaultServiceFee, r.DefaultLaundryFee,
        r.DefaultElectricityUnitPrice, r.DefaultWaterUnitPrice, r.RentalStatus, r.IsActive,
        ISNULL(t.CurrentTenantCount, 0) AS CurrentTenantCount, t.TenantNames
    FROM dbo.Rooms AS r
    INNER JOIN dbo.Properties AS p ON p.PropertyId = r.PropertyId
    LEFT JOIN dbo.v_CurrentRoomTenants AS t ON t.RoomId = r.RoomId
"""


def room_list(property_id: int | None = None) -> list[Any]:
    clause, params = property_filter("r.PropertyId", property_id)
    return rows(
        f"""{ROOM_SELECT}
        WHERE r.IsActive = 1 AND p.IsActive = 1 {clause}
        ORDER BY p.PropertyName, r.RoomCode;
        """,
        params,
    )


def get_room(room_id: int) -> Any | None:
    return one(f"{ROOM_SELECT} WHERE r.RoomId = ?;", (room_id,))


def create_room(
    property_id: int,
    room_code: str,
    room_name: str,
    rent_amount: Decimal,
    service_fee: Decimal,
    laundry_fee: Decimal,
    electricity_price: Decimal,
    water_price: Decimal,
) -> int:
    with connect() as cnxn:
        cursor = cnxn.cursor()
        cursor.execute(
            """
            INSERT INTO dbo.Rooms
                (PropertyId, RoomCode, RoomName, RentAmount, DefaultServiceFee, DefaultLaundryFee,
                 DefaultElectricityUnitPrice, DefaultWaterUnitPrice, RentalStatus)
            OUTPUT INSERTED.RoomId
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, N'VACANT');
            """,
            property_id, room_code, room_name, rent_amount, service_fee, laundry_fee, electricity_price, water_price,
        )
        room_id = int(cursor.fetchone()[0])
        cursor.execute(
            """
            INSERT INTO dbo.RoomPricePeriods
                (RoomId, EffectiveFromYear, EffectiveFromMonth, RentAmount, ServiceFee, LaundryFee, ElectricityUnitPrice, WaterUnitPrice, Note)
            VALUES (?, 2000, 1, ?, ?, ?, ?, ?, N'Gia mac dinh tu thong tin phong');
            """,
            room_id, rent_amount, service_fee, laundry_fee, electricity_price, water_price,
        )
        cnxn.commit()
    return room_id


def update_room_info(room_id: int, property_id: int, room_code: str, room_name: str) -> None:
    execute(
        """
        UPDATE dbo.Rooms
        SET PropertyId = ?, RoomCode = ?, RoomName = ?, UpdatedAt = SYSDATETIME()
        WHERE RoomId = ?;
        """,
        (property_id, room_code, room_name, room_id),
    )


def deactivate_room(room_id: int) -> None:
    execute(
        "UPDATE dbo.Rooms SET IsActive = 0, RentalStatus = N'INACTIVE', UpdatedAt = SYSDATETIME() WHERE RoomId = ?;",
        (room_id,),
    )


def update_room_prices(
    room_id: int,
    rent_amount: Decimal,
    service_fee: Decimal,
    laundry_fee: Decimal,
    electricity_price: Decimal,
    water_price: Decimal,
    rental_status: str,
    from_year: int,
    from_month: int,
    to_year: int | None,
    to_month: int | None,
) -> int:
    """Cập nhật giá phòng, lưu giai đoạn đơn giá và tính lại các hóa đơn trong giai đoạn. Trả về số hóa đơn được tính lại."""
    with connect() as cnxn:
        cursor = cnxn.cursor()
        cursor.execute(
            """
            UPDATE dbo.Rooms
            SET RentAmount = ?, DefaultServiceFee = ?, DefaultLaundryFee = ?,
                DefaultElectricityUnitPrice = ?, DefaultWaterUnitPrice = ?, RentalStatus = ?,
                UpdatedAt = SYSDATETIME()
            WHERE RoomId = ?;
            """,
            rent_amount, service_fee, laundry_fee, electricity_price, water_price, rental_status, room_id,
        )
        prices = (rent_amount, service_fee, laundry_fee, electricity_price, water_price)
        period_id = _upsert_price_period(cursor, room_id, prices, from_year, from_month, to_year, to_month)
        updated = _sync_bills_for_period(cursor, period_id, room_id, prices, from_year, from_month, to_year, to_month)
        cnxn.commit()
    return updated


def _upsert_price_period(
    cursor: pyodbc.Cursor,
    room_id: int,
    prices: tuple[Decimal, ...],
    from_year: int,
    from_month: int,
    to_year: int | None,
    to_month: int | None,
) -> int:
    cursor.execute(
        """
        UPDATE dbo.RoomPricePeriods
        SET EffectiveToYear = ?, EffectiveToMonth = ?,
            RentAmount = ?, ServiceFee = ?, LaundryFee = ?, ElectricityUnitPrice = ?, WaterUnitPrice = ?,
            Note = N'Cap nhat tu menu phong', UpdatedAt = SYSDATETIME()
        WHERE RoomId = ? AND EffectiveFromYear = ? AND EffectiveFromMonth = ?;
        """,
        to_year, to_month, *prices, room_id, from_year, from_month,
    )
    if cursor.rowcount == 0:
        cursor.execute(
            """
            INSERT INTO dbo.RoomPricePeriods
                (RoomId, EffectiveFromYear, EffectiveFromMonth, EffectiveToYear, EffectiveToMonth,
                 RentAmount, ServiceFee, LaundryFee, ElectricityUnitPrice, WaterUnitPrice, Note)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, N'Cap nhat tu menu phong');
            """,
            room_id, from_year, from_month, to_year, to_month, *prices,
        )
    cursor.execute(
        "SELECT RoomPricePeriodId FROM dbo.RoomPricePeriods WHERE RoomId = ? AND EffectiveFromYear = ? AND EffectiveFromMonth = ?;",
        room_id, from_year, from_month,
    )
    return int(cursor.fetchone().RoomPricePeriodId)


def _sync_bills_for_period(
    cursor: pyodbc.Cursor,
    period_id: int,
    room_id: int,
    prices: tuple[Decimal, ...],
    from_year: int,
    from_month: int,
    to_year: int | None,
    to_month: int | None,
) -> int:
    """Áp giá mới cho hóa đơn trong giai đoạn, trừ những tháng đã có giai đoạn bắt đầu muộn hơn phủ lên."""
    cursor.execute(
        """
        UPDATE bills
        SET RentAmount = ?, ServiceFee = ?, LaundryFee = ?, ElectricityUnitPrice = ?, WaterUnitPrice = ?,
            UpdatedAt = SYSDATETIME()
        FROM dbo.RoomMonthlyBills AS bills
        INNER JOIN dbo.BillingMonths AS months ON months.BillingMonthId = bills.BillingMonthId
        WHERE bills.RoomId = ?
          AND (months.YearNumber > ? OR (months.YearNumber = ? AND months.MonthNumber >= ?))
          AND (? IS NULL OR months.YearNumber < ? OR (months.YearNumber = ? AND months.MonthNumber <= ?))
          AND NOT EXISTS
          (
              SELECT 1
              FROM dbo.RoomPricePeriods AS later
              WHERE later.RoomId = bills.RoomId
                AND later.RoomPricePeriodId <> ?
                AND (later.EffectiveFromYear > ? OR (later.EffectiveFromYear = ? AND later.EffectiveFromMonth > ?))
                AND (later.EffectiveFromYear < months.YearNumber
                     OR (later.EffectiveFromYear = months.YearNumber AND later.EffectiveFromMonth <= months.MonthNumber))
                AND (later.EffectiveToYear IS NULL
                     OR later.EffectiveToYear > months.YearNumber
                     OR (later.EffectiveToYear = months.YearNumber AND later.EffectiveToMonth >= months.MonthNumber))
          );
        """,
        *prices,
        room_id,
        from_year, from_year, from_month,
        to_year, to_year, to_year, to_month,
        period_id,
        from_year, from_year, from_month,
    )
    return max(cursor.rowcount or 0, 0)


def room_price_periods_by_room() -> dict[int, list[Any]]:
    result: dict[int, list[Any]] = {}
    for period in rows(
        f"SELECT {PERIOD_COLUMNS} FROM dbo.RoomPricePeriods "
        "ORDER BY RoomId, EffectiveFromYear DESC, EffectiveFromMonth DESC, RoomPricePeriodId DESC;"
    ):
        result.setdefault(int(period.RoomId), []).append(period)
    return result


# ----- Khách thuê -----

def tenant_list(property_id: int | None = None) -> list[Any]:
    clause, params = property_filter("r.PropertyId", property_id)
    return rows(
        f"""
        SELECT t.TenantId, t.RoomId, r.RoomCode, r.RoomName, p.PropertyName, p.PropertyType,
               t.FullName, t.Phone, t.Email, t.ZaloPhone, t.ZaloUserId, t.CitizenId, t.PermanentAddress,
               t.MoveInDate, t.MoveOutDate, t.RentAmount, t.ServiceFee, t.IsCurrent, t.Note
        FROM dbo.Tenants AS t
        INNER JOIN dbo.Rooms AS r ON r.RoomId = t.RoomId
        INNER JOIN dbo.Properties AS p ON p.PropertyId = r.PropertyId
        WHERE r.IsActive = 1 {clause}
        ORDER BY t.IsCurrent DESC, p.PropertyName, r.RoomCode, t.FullName;
        """,
        params,
    )


def save_tenant(tenant_id: int | None, fields: dict[str, Any]) -> None:
    columns = list(fields)
    values = [fields[column] for column in columns]
    with connect() as cnxn:
        cursor = cnxn.cursor()
        if tenant_id:
            assignments = ", ".join(f"{column} = ?" for column in columns)
            cursor.execute(
                f"UPDATE dbo.Tenants SET {assignments}, UpdatedAt = SYSDATETIME() WHERE TenantId = ?;",
                *values, tenant_id,
            )
        else:
            cursor.execute(
                f"INSERT INTO dbo.Tenants ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)});",
                *values,
            )
        cnxn.commit()


def end_tenancy(tenant_id: int) -> None:
    execute(
        """
        UPDATE dbo.Tenants
        SET IsCurrent = 0, MoveOutDate = COALESCE(MoveOutDate, CAST(GETDATE() AS DATE)), UpdatedAt = SYSDATETIME()
        WHERE TenantId = ?;
        """,
        (tenant_id,),
    )


def sync_room_status(room_id: int) -> None:
    """Phòng có khách đang thuê -> Đang thuê; hết khách -> Trống (giữ nguyên Đặt cọc/Bảo trì nếu đang đặt tay)."""
    execute(
        """
        UPDATE r
        SET RentalStatus = CASE
                WHEN EXISTS (SELECT 1 FROM dbo.Tenants AS t WHERE t.RoomId = r.RoomId AND t.IsCurrent = 1) THEN N'OCCUPIED'
                WHEN r.RentalStatus = N'OCCUPIED' THEN N'VACANT'
                ELSE r.RentalStatus
            END,
            UpdatedAt = SYSDATETIME()
        FROM dbo.Rooms AS r
        WHERE r.RoomId = ? AND r.IsActive = 1;
        """,
        (room_id,),
    )


def tenant_contract(room_id: int, year: int | None = None, month: int | None = None) -> Any | None:
    """Lượt thuê khớp tháng (nếu truyền year/month), ngược lại là lượt đang thuê."""
    if year is not None and month is not None:
        month_start, month_end = month_bounds(year, month)
        condition = "AND (MoveInDate IS NULL OR MoveInDate <= ?) AND (MoveOutDate IS NULL OR MoveOutDate >= ?)"
        params: tuple[Any, ...] = (room_id, month_end, month_start)
    else:
        condition, params = "AND IsCurrent = 1", (room_id,)
    return one(
        f"""
        SELECT TOP 1 TenantId, FullName, MoveInDate, MoveOutDate, RentAmount, ServiceFee
        FROM dbo.Tenants
        WHERE RoomId = ? {condition}
        ORDER BY CASE WHEN MoveInDate IS NULL THEN 1 ELSE 0 END, MoveInDate DESC, TenantId DESC;
        """,
        params,
    )


# ----- Tháng & giá -----

def get_month(year: int, month: int) -> Any | None:
    return one(
        """
        SELECT BillingMonthId, YearNumber, MonthNumber, ElectricityUnitPrice, WaterUnitPrice, DefaultServiceFee
        FROM dbo.BillingMonths WHERE YearNumber = ? AND MonthNumber = ?;
        """,
        (year, month),
    )


def save_month(year: int, month: int, electricity_price: Decimal, water_price: Decimal, service_fee: Decimal) -> None:
    with connect() as cnxn:
        cursor = cnxn.cursor()
        cursor.execute(
            """
            UPDATE dbo.BillingMonths
            SET ElectricityUnitPrice = ?, WaterUnitPrice = ?, DefaultServiceFee = ?, UpdatedAt = SYSDATETIME()
            WHERE YearNumber = ? AND MonthNumber = ?;
            """,
            electricity_price, water_price, service_fee, year, month,
        )
        if cursor.rowcount == 0:
            cursor.execute(
                """
                INSERT INTO dbo.BillingMonths (YearNumber, MonthNumber, ElectricityUnitPrice, WaterUnitPrice, DefaultServiceFee)
                VALUES (?, ?, ?, ?, ?);
                """,
                year, month, electricity_price, water_price, service_fee,
            )
        cnxn.commit()


def ensure_month(year: int, month: int) -> Any:
    month_data = get_month(year, month)
    if month_data is None:
        save_month(year, month, DEFAULT_ELECTRICITY_PRICE, DEFAULT_WATER_PRICE, DEFAULT_SERVICE_FEE)
        month_data = get_month(year, month)
    return month_data


def is_seed_price_period(period: Any | None) -> bool:
    return period is not None and int(period.EffectiveFromYear) == 2000 and int(period.EffectiveFromMonth) == 1


def room_price_period_for_month(room_id: int, year: int, month: int) -> Any | None:
    return one(
        f"""
        SELECT TOP 1 {PERIOD_COLUMNS}
        FROM dbo.RoomPricePeriods
        WHERE RoomId = ?
          AND (EffectiveFromYear < ? OR (EffectiveFromYear = ? AND EffectiveFromMonth <= ?))
          AND (EffectiveToYear IS NULL OR EffectiveToYear > ? OR (EffectiveToYear = ? AND EffectiveToMonth >= ?))
        ORDER BY EffectiveFromYear DESC, EffectiveFromMonth DESC, RoomPricePeriodId DESC;
        """,
        (room_id, year, year, month, year, year, month),
    )


def room_prices_for_month(
    room: Any | None, year: int, month: int, month_data: Any | None = None
) -> tuple[Decimal, Decimal, Decimal, Decimal, Decimal]:
    """(tiền thuê, dịch vụ, máy giặt, giá điện, giá nước) áp dụng cho phòng trong tháng.

    Thứ tự ưu tiên: giai đoạn đơn giá đặt tay > giá thỏa thuận của lượt thuê > giá mặc định của phòng.
    Phòng không có khách trong tháng thì chỉ tính điện nước.
    """
    if room is None:
        return ZERO, ZERO, ZERO, ZERO, ZERO

    electricity_price = Decimal(room.DefaultElectricityUnitPrice or 0)
    water_price = Decimal(room.DefaultWaterUnitPrice or 0)
    if month_data is not None:
        electricity_price = electricity_price if electricity_price > 0 else Decimal(month_data.ElectricityUnitPrice)
        water_price = water_price if water_price > 0 else Decimal(month_data.WaterUnitPrice)
    laundry_fee = Decimal(room.DefaultLaundryFee or 0)

    period = room_price_period_for_month(int(room.RoomId), year, month)
    if period is not None:
        electricity_price = Decimal(period.ElectricityUnitPrice)
        water_price = Decimal(period.WaterUnitPrice)
        laundry_fee = Decimal(period.LaundryFee)

    contract = tenant_contract(int(room.RoomId), year, month)
    no_tenant = contract is None and room.RentalStatus != "OCCUPIED"

    if period is not None and not is_seed_price_period(period):
        if no_tenant:
            return ZERO, ZERO, ZERO, electricity_price, water_price
        return Decimal(period.RentAmount), Decimal(period.ServiceFee), laundry_fee, electricity_price, water_price
    if contract is not None:
        return Decimal(contract.RentAmount), Decimal(contract.ServiceFee), laundry_fee, electricity_price, water_price
    if no_tenant:
        return ZERO, ZERO, ZERO, electricity_price, water_price
    return (
        Decimal(room.RentAmount),
        Decimal(room.DefaultServiceFee),
        Decimal(room.DefaultLaundryFee or 0),
        electricity_price,
        water_price,
    )


# ----- Hóa đơn -----

def previous_reading(room_id: int, year: int, month: int) -> Any | None:
    previous_year, previous_month = shift_month(year, month, -1)
    return one(
        """
        SELECT b.ElectricNew, b.WaterNew
        FROM dbo.RoomMonthlyBills AS b
        INNER JOIN dbo.BillingMonths AS bm ON bm.BillingMonthId = b.BillingMonthId
        WHERE b.RoomId = ? AND bm.YearNumber = ? AND bm.MonthNumber = ?;
        """,
        (room_id, previous_year, previous_month),
    )


def month_bills(year: int, month: int, property_id: int | None = None) -> list[Any]:
    clause, params = property_filter("PropertyId", property_id)
    return rows(
        f"""
        SELECT {BILL_COLUMNS} FROM dbo.v_MonthlyRoomBills
        WHERE YearNumber = ? AND MonthNumber = ? {clause}
        ORDER BY PropertyName, RoomCode;
        """,
        (year, month, *params),
    )


def get_bill(bill_id: int) -> Any | None:
    return one(f"SELECT {BILL_COLUMNS} FROM dbo.v_MonthlyRoomBills WHERE RoomMonthlyBillId = ?;", (bill_id,))


def bill_for_room_month(room_id: int, year: int, month: int) -> Any | None:
    return one(
        f"SELECT {BILL_COLUMNS} FROM dbo.v_MonthlyRoomBills WHERE RoomId = ? AND YearNumber = ? AND MonthNumber = ?;",
        (room_id, year, month),
    )


def billed_room_ids(year: int, month: int) -> set[int]:
    return {
        int(item.RoomId)
        for item in rows(
            """
            SELECT b.RoomId FROM dbo.RoomMonthlyBills AS b
            INNER JOIN dbo.BillingMonths AS bm ON bm.BillingMonthId = b.BillingMonthId
            WHERE bm.YearNumber = ? AND bm.MonthNumber = ?;
            """,
            (year, month),
        )
    }


def next_unbilled_room(year: int, month: int, current_room_id: int, property_id: int | None) -> Any | None:
    billed = billed_room_ids(year, month)
    rooms = room_list(property_id)
    position = next((i for i, room in enumerate(rooms) if room.RoomId == current_room_id), -1)
    ordered = rooms[position + 1:] + rooms[: position + 1]
    return next((room for room in ordered if room.RoomId not in billed), None)


def save_bill(
    room: Any,
    year: int,
    month: int,
    electric_old: Decimal,
    electric_new: Decimal,
    water_old: Decimal,
    water_new: Decimal,
    note: str | None,
) -> None:
    month_data = ensure_month(year, month)
    prices = room_prices_for_month(room, year, month, month_data)
    readings = (electric_old, electric_new, water_old, water_new, note)
    with connect() as cnxn:
        cursor = cnxn.cursor()
        cursor.execute(
            """
            UPDATE dbo.RoomMonthlyBills
            SET RentAmount = ?, ServiceFee = ?, LaundryFee = ?, ElectricityUnitPrice = ?, WaterUnitPrice = ?,
                ElectricOld = ?, ElectricNew = ?, WaterOld = ?, WaterNew = ?, Note = ?, UpdatedAt = SYSDATETIME()
            WHERE BillingMonthId = ? AND RoomId = ?;
            """,
            *prices, *readings, month_data.BillingMonthId, room.RoomId,
        )
        if cursor.rowcount == 0:
            cursor.execute(
                """
                INSERT INTO dbo.RoomMonthlyBills
                    (RentAmount, ServiceFee, LaundryFee, ElectricityUnitPrice, WaterUnitPrice,
                     ElectricOld, ElectricNew, WaterOld, WaterNew, Note, BillingMonthId, RoomId)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                *prices, *readings, month_data.BillingMonthId, room.RoomId,
            )
        cnxn.commit()


def report_month_summaries(year: int, property_id: int | None = None) -> list[Any]:
    clause, params = property_filter("bills.PropertyId", property_id)
    return rows(
        f"""
        WITH MonthNumbers AS
        (
            SELECT MonthNumber FROM (VALUES (1), (2), (3), (4), (5), (6), (7), (8), (9), (10), (11), (12)) AS m(MonthNumber)
        )
        SELECT m.MonthNumber,
               COUNT(bills.RoomMonthlyBillId) AS BillCount,
               COALESCE(SUM(bills.TotalAmount), 0) AS TotalAmount
        FROM MonthNumbers AS m
        LEFT JOIN dbo.v_MonthlyRoomBills AS bills
            ON bills.YearNumber = ? AND bills.MonthNumber = m.MonthNumber {clause}
        GROUP BY m.MonthNumber
        ORDER BY m.MonthNumber;
        """,
        (year, *params),
    )


def log_bill_delivery(bill_id: int, channel: str, recipient: str | None, status: str, error_message: str | None = None) -> None:
    execute(
        "INSERT INTO dbo.BillDeliveryLogs (RoomMonthlyBillId, Channel, Recipient, Status, ErrorMessage) VALUES (?, ?, ?, ?, ?);",
        (bill_id, channel, recipient, status, (error_message or "")[:1000] or None),
    )


# ----- Cấu hình thanh toán -----

def payment_settings() -> Any | None:
    return one(
        """
        SELECT PaymentSettingsId, QrImage, QrMimeType, QrFileName, AccountInfo, SenderName, FromEmail,
               SmtpHost, SmtpPort, SmtpUseTls, SmtpUsername, SmtpPassword, UpdatedAt
        FROM dbo.PaymentSettings WHERE PaymentSettingsId = 1;
        """
    )


def save_email_settings(sender_name: str, from_email: str | None, host: str | None, port: int, use_tls: bool, username: str | None, password: str | None) -> None:
    execute(
        """
        UPDATE dbo.PaymentSettings
        SET SenderName = ?, FromEmail = ?, SmtpHost = ?, SmtpPort = ?, SmtpUseTls = ?, SmtpUsername = ?, SmtpPassword = ?,
            UpdatedAt = SYSDATETIME()
        WHERE PaymentSettingsId = 1;
        """,
        (sender_name, from_email, host, port, 1 if use_tls else 0, username, password),
    )


def save_qr_settings(account_info: str | None, qr: tuple[bytes, str, str] | None) -> None:
    if qr is None:
        execute(
            "UPDATE dbo.PaymentSettings SET AccountInfo = ?, UpdatedAt = SYSDATETIME() WHERE PaymentSettingsId = 1;",
            (account_info,),
        )
        return
    data, mime_type, file_name = qr
    execute(
        """
        UPDATE dbo.PaymentSettings
        SET QrImage = ?, QrMimeType = ?, QrFileName = ?, AccountInfo = ?, UpdatedAt = SYSDATETIME()
        WHERE PaymentSettingsId = 1;
        """,
        (pyodbc.Binary(data), mime_type, file_name, account_info),
    )
