import uuid
from datetime import datetime, timezone, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.logging import logger
from app.auth.repository import get_user_by_email, create_token_record, create_user, get_token_by_jti, revoke_token_tree
from app.core.exceptions import UserEmailAlreadyExists, UserNotFound, InvalidCredentials, TokenNotFound, \
    TokenAlreadyExpired
from app.auth.utils import hash_password, create_access_token, verify_password
from app.models.auth import User, Token
from app.core.config import settings


async def register_user(db: AsyncSession, email: str, password: str, name: str | None,
                        phone_number: str | None) -> User | None:
    user = await get_user_by_email(email, db)
    if user:
        logger.warning(f"User with email {email} already exists")
        raise UserEmailAlreadyExists(email)
    hashed_pass = hash_password(password)
    user = User(
        email=email,
        password_hash=hashed_pass,
        name=name,
        phone=phone_number
    )
    user = await create_user(user, db)
    logger.info(f"Created new user with email {email}")
    return user


async def login(db: AsyncSession, email: str, password: str):
    user = await get_user_by_email(email, db)
    if not user:
        logger.warning(f"User with email {email} does not exist")
        raise UserNotFound(email)
    if not verify_password(password, user.password_hash):
        logger.warning(f"User with email {email} does not exist")
        raise InvalidCredentials(email)
    jti = str(uuid.uuid4())
    token = Token(jti=jti,
                  user_id=user.id,
                  merchant_id=None,
                  parent_token_id=None,
                  scopes=['*'],
                  expires_at=datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
                  )
    token = await create_token_record(token, db)
    jwt = create_access_token(user.id, jti, token.scopes, token.merchant_id)
    logger.info(f'jwt created for user with email {email}, jti: {jti}')
    return jwt


async def revoke_token(db: AsyncSession, jti: str, revoked_by: uuid.UUID, reason: str) -> int:
    token = await get_token_by_jti(jti, db)
    if not token:
        logger.warning(f"Token with jti {jti} does not exist")
        raise TokenNotFound(jti)
    if token.is_revoked:
        logger.warning(f"Token with jti {jti} already revoked")
        raise TokenAlreadyExpired(jti)
    revoked_tkns = await revoke_token_tree(token.id, revoked_by, reason, db)
    logger.info(f'revoked {revoked_tkns} tokens with jti {jti}')
    return revoked_tkns
