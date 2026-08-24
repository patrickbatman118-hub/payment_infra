import bcrypt
from jose import jwt, JWTError, ExpiredSignatureError
from datetime import datetime, timedelta, timezone
import uuid
from app.core.config import settings
def hash_password(password: str) -> str:
    hashed_pass = bcrypt.hashpw(password.encode(),bcrypt.gensalt()).decode()
    return hashed_pass

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode(), hashed_password.encode())

def create_access_token(user_id: uuid.UUID, jti: str, scopes: list[str], merchant_id: uuid.UUID | None) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
    to_encode = dict(user_id=user_id, jti=jti, scopes=scopes, merchant_id=merchant_id, exp=expire, type='access',
                     iat=datetime.now(timezone.utc))
    encoded_jwt = jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)
    return encoded_jwt

def decode_access_token(token: str):
    try:
        decoded_jwt = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        return decoded_jwt
    except ExpiredSignatureError:
        raise
    except JWTError:
        raise