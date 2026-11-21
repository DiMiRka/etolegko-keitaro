from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.security import MIN_PASSWORD_LENGTH, CurrentUser, hash_password, verify_password
from app.models import User


def _by_name(username: str):
    return select(User).where(func.lower(User.username) == username.strip().lower())


async def authenticate(session: AsyncSession, username: str, password: str) -> CurrentUser | None:
    user = await session.scalar(_by_name(username))
    if user is None or not user.is_active or not verify_password(password, user.password_hash):
        return None
    return CurrentUser(user.id, user.username)


def _check_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise AppError(f"Пароль должен быть не короче {MIN_PASSWORD_LENGTH} символов")


async def create_user(session: AsyncSession, username: str, password: str) -> User:
    username = username.strip()
    if not username:
        raise AppError("Укажите имя пользователя")
    _check_password(password)
    if await session.scalar(_by_name(username)) is not None:
        raise AppError(f"Пользователь {username} уже есть")
    user = User(username=username, password_hash=hash_password(password), is_active=True)
    session.add(user)
    await session.commit()
    return user


async def set_password(session: AsyncSession, username: str, password: str) -> None:
    _check_password(password)
    user = await session.scalar(_by_name(username))
    if user is None:
        raise AppError(f"Пользователя {username} нет")
    user.password_hash = hash_password(password)
    await session.commit()


async def users_count(session: AsyncSession) -> int:
    return await session.scalar(select(func.count(User.id))) or 0
