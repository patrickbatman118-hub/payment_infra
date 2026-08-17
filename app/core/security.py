import bcrypt
from jose import jwt, JWTError
from datetime import datetime, timedelta, timezone
import uuid
from app.core.config import settings
def hash_password(password: str) -> str:
    hashed_pass = bcrypt.hashpw(password.encode(),bcrypt.gensalt()).decode()
    return hashed_pass

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode(), hashed_password.encode())

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
    to_encode.update({"exp": expire, "type": 'access', 'jti': str(uuid.uuid4()), "iat": datetime.now(timezone.utc)})
    encoded_jwt = jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)
    return encoded_jwt

def decode_access_token(token: str):
    try:
        decoded_jwt = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        return decoded_jwt
    except JWTError:
        return None