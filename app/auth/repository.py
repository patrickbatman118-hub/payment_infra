from app.models.auth import User, Token
from app.core.database import AsyncSession
from sqlalchemy import select



async def get_user_by_email(email: str,db: AsyncSession) -> User | None:
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    return user

async def create_user(user:User, db: AsyncSession) -> User:
    db.add(user)
    await db.commit()
    return user

async def create_token_record(token: Token, db: AsyncSession) -> Token:
    db.add(token)
    await db.commit()
    return token
