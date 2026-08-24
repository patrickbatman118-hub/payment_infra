from app.models.auth import User, Token
from app.core.database import AsyncSession
from app.core.logging import logger
from sqlalchemy import select
from fastapi import HTTPException


async def get_user_by_email(email: str,db: AsyncSession) -> User | None:
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if not user:
        logger.warning(f"User with email {email} not found")
        raise HTTPException(status_code=404, detail="User not found")
    return user

async def create_user(user:User, db: AsyncSession) -> User:
    db.add(User)
    await db.commit()
    return user

async def create_token_record(token: str, db: AsyncSession) -> Token:
    token = Token(jti=token)
    db.add(token)
    await db.commit()
    return token
