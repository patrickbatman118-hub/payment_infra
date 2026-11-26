import uuid
from sqlalchemy import text
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


async def revoke_token_tree(token_id: uuid.UUID, revoked_by: uuid.UUID, reason: str, db: AsyncSession) -> int:
    result = await db.execute(
        text("""
             WITH RECURSIVE token_tree AS (SELECT id
                                           FROM tokens
                                           WHERE id = :token_id
                                           UNION ALL
                                           SELECT t.id
                                           FROM tokens t
                                                    JOIN token_tree tt ON t.parent_token_id = tt.id)
             UPDATE tokens
             SET is_revoked        = TRUE,
                 revoked_at        = NOW(),
                 revoked_by        = :revoked_by,
                 revocation_reason = :reason
             WHERE id IN (SELECT id FROM token_tree)
               AND is_revoked = FALSE RETURNING id
             """),
        {"token_id": str(token_id), "revoked_by": str(revoked_by), "reason": reason}
    )
    await db.commit()
    revoked_ids = result.scalars().all()
    return len(revoked_ids)
