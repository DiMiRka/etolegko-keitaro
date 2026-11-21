import argparse
import asyncio
import getpass
import sys

from app import auth
from app.config import get_settings
from app.db import make_engine, make_sessionmaker
from app.errors import AppError


def _password(args) -> str:
    if args.password:
        return args.password
    first = getpass.getpass("Пароль: ")
    if first != getpass.getpass("Повторите пароль: "):
        raise AppError("Пароли не совпадают")
    return first


async def _run(args) -> None:
    engine = make_engine(get_settings().database_url)
    try:
        async with make_sessionmaker(engine)() as session:
            if args.command == "create-user":
                await auth.create_user(session, args.username, _password(args))
                print(f"Пользователь {args.username} создан")
            elif args.command == "set-password":
                await auth.set_password(session, args.username, _password(args))
                print(f"Пароль пользователя {args.username} обновлён")
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description="Пользователи сервиса")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (("create-user", "создать пользователя"), ("set-password", "сменить пароль")):
        cmd = sub.add_parser(name, help=help_text)
        cmd.add_argument("username")
        cmd.add_argument("--password", help="пароль; без флага будет запрошен в терминале")
    args = parser.parse_args(argv)
    try:
        asyncio.run(_run(args))
    except AppError as e:
        print(f"Ошибка: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
