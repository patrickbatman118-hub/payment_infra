import uuid

from app.core.exceptions import TokenNotFound
from app.models.auth import User, Token
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.logging import logger


async def get_user_by_email(email: str, db: AsyncSession) -> User | None:
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    return user


async def create_user(user: User, db: AsyncSession) -> User:
    db.add(user)
    await db.commit()
    return user


async def create_token_record(token: Token, db: AsyncSession) -> Token:
    db.add(token)
    await db.commit()
    return token


async def get_token_by_jti(jti: str, db: AsyncSession) -> Token | None:
    result = await db.execute(select(Token).where(Token.jti == jti))
    token = result.scalar_one_or_none()
    return token

async def revoke_token_tree(token_id: uuid.UUID, revoked_by: uuid.UUID, reason: str, db: AsyncSession) -> None: