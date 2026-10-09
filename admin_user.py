import argparse
import getpass

from timeclock.database import (
    create_admin_user,
    init_database,
    list_admin_users,
    reset_admin_password,
    set_admin_user_active,
)


def main():
    parser = argparse.ArgumentParser(description="Manage TimeClockPi administrator accounts")
    parser.add_argument("command", choices=["create", "reset-password", "list", "enable", "disable"])
    parser.add_argument("username", nargs="?")
    parser.add_argument("--role", choices=["admin", "supervisor"], default="admin", help="Rol del nou usuari")
    args = parser.parse_args()

    init_database()

    if args.command != "list" and not args.username:
        parser.error("aquest comandament requereix un nom d'usuari")

    if args.command == "list":
        for user in list_admin_users():
            status = "actiu" if user["active"] else "inactiu"
            print(f'{user["username"]}\t{user["role"]}\t{status}')
    elif args.command == "create":
        password = getpass.getpass("Contrasenya: ")
        confirmation = getpass.getpass("Repeteix la contrasenya: ")
        if password != confirmation:
            raise SystemExit("Les contrasenyes no coincideixen")
        try:
            create_admin_user(args.username, password, role=args.role)
        except ValueError as error:
            raise SystemExit(str(error)) from error
        print(f"Usuari {args.username!r} creat amb rol {args.role}.")
    elif args.command == "reset-password":
        password = getpass.getpass("Nova contrasenya: ")
        confirmation = getpass.getpass("Repeteix la nova contrasenya: ")
        if password != confirmation:
            raise SystemExit("Les contrasenyes no coincideixen")
        try:
            reset_admin_password(args.username, password)
        except ValueError as error:
            raise SystemExit(str(error)) from error
        print(f"Contrasenya de l'administrador {args.username!r} actualitzada.")
    elif args.command in {"enable", "disable"}:
        active = args.command == "enable"
        try:
            set_admin_user_active(args.username, active)
        except ValueError as error:
            raise SystemExit(str(error)) from error
        status = "activat" if active else "desactivat"
        print(f"Administrador {args.username!r} {status}.")


if __name__ == "__main__":
    main()
