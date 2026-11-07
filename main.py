"""Lệnh quản trị:

    python main.py init-db        tạo/cập nhật database (an toàn khi chạy lại)
    python main.py create-owner   tạo tài khoản chủ nhà, hoặc đổi mật khẩu nếu tài khoản đã có
"""
import argparse
import getpass
import sys

from src.db import init_database


def create_owner(username: str | None) -> None:
    from src.auth import set_owner_password

    username = (username or input("Ten dang nhap [admin]: ").strip() or "admin")
    password = getpass.getpass("Mat khau (it nhat 8 ky tu): ")
    if password != getpass.getpass("Nhap lai mat khau: "):
        raise ValueError("Hai lan nhap mat khau khong khop.")
    created = set_owner_password(username, password)
    print(f"Da {'tao tai khoan' if created else 'doi mat khau cho'} '{username}'. Cac phien dang nhap cu da bi dang xuat.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Quan ly cho thue nha / phong")
    parser.add_argument("command", choices=["init-db", "create-owner"],
                        help="init-db: tao/cap nhat database; create-owner: tao tai khoan / doi mat khau chu nha")
    parser.add_argument("--username", help="Ten dang nhap (dung voi create-owner)")
    args = parser.parse_args()
    if args.command == "init-db":
        init_database()
        print("Da tao/cap nhat cau truc database.")
    else:
        init_database()
        create_owner(args.username)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Loi: {exc}")
        sys.exit(1)
