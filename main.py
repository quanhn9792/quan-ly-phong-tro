"""Lệnh quản trị: `python main.py init-db` tạo/cập nhật database (an toàn khi chạy lại)."""
import argparse
import sys

from src.db import init_database


def main() -> None:
    parser = argparse.ArgumentParser(description="Quan ly cho thue nha / phong")
    parser.add_argument("command", choices=["init-db"], help="init-db: tao/cap nhat cau truc database")
    parser.parse_args()
    init_database()
    print("Da tao/cap nhat cau truc database.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Loi: {exc}")
        sys.exit(1)
