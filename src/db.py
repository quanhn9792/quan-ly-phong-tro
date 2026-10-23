from __future__ import annotations

import os
import re
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Sequence

import pyodbc


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_FILE = PROJECT_ROOT / "database" / "schema.sql"
PREFERRED_DRIVERS = [
    "ODBC Driver 18 for SQL Server",
    "ODBC Driver 17 for SQL Server",
    "SQL Server Native Client 11.0",
    "SQL Server",
]


def database_name() -> str:
    return os.getenv("MSSQL_DATABASE", "QuanLyPhongTro")


def pick_driver() -> str:
    configured = os.getenv("MSSQL_DRIVER")
    if configured:
        return configured
    installed = set(pyodbc.drivers())
    for driver in PREFERRED_DRIVERS:
        if driver in installed:
            return driver
    raise RuntimeError(
        "Khong tim thay ODBC driver cho SQL Server. Hay cai 'ODBC Driver 18 for SQL Server' "
        "hoac dat bien moi truong MSSQL_DRIVER."
    )


def connection_string(database: str | None = None) -> str:
    server = os.getenv("MSSQL_SERVER", r"(localdb)\QuanLyPhongTro2025")
    parts = [
        f"DRIVER={{{pick_driver()}}}",
        f"SERVER={server}",
        f"DATABASE={database or database_name()}",
        "TrustServerCertificate=yes",
    ]
    uid = os.getenv("MSSQL_USERNAME")
    pwd = os.getenv("MSSQL_PASSWORD")
    if uid and pwd:
        parts.extend([f"UID={uid}", f"PWD={pwd}"])
    else:
        parts.append("Trusted_Connection=yes")
    return ";".join(parts) + ";"


@contextmanager
def connect(database: str | None = None, autocommit: bool = False):
    cnxn = pyodbc.connect(connection_string(database), autocommit=autocommit)
    try:
        yield cnxn
    finally:
        cnxn.close()


def rows(query: str, params: Sequence[Any] = ()) -> list[Any]:
    with connect() as cnxn:
        return list(cnxn.cursor().execute(query, params).fetchall())


def one(query: str, params: Sequence[Any] = ()) -> Any | None:
    with connect() as cnxn:
        return cnxn.cursor().execute(query, params).fetchone()


def execute(query: str, params: Sequence[Any] = ()) -> int:
    with connect() as cnxn:
        cursor = cnxn.cursor().execute(query, params)
        cnxn.commit()
        return cursor.rowcount


def split_sql_batches(script: str) -> Iterable[str]:
    for batch in re.split(r"^\s*GO\s*;?\s*$", script, flags=re.IGNORECASE | re.MULTILINE):
        batch = batch.strip()
        if batch:
            yield batch


def init_database() -> None:
    database = database_name()
    with connect(database="master", autocommit=True) as cnxn:
        cnxn.cursor().execute(
            f"IF DB_ID(N'{database.replace(chr(39), chr(39) * 2)}') IS NULL "
            f"EXEC(N'CREATE DATABASE [{database.replace(']', ']]')}]');"
        )

    script = SCHEMA_FILE.read_text(encoding="utf-8")
    with connect(autocommit=True) as cnxn:
        cursor = cnxn.cursor()
        for batch in split_sql_batches(script):
            cursor.execute(batch)
