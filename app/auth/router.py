from fastapi import APIRouter, Depends
from service import register_user, login
from app.core.database import get_db, AsyncSession
from app.schemas.auth import RegisterRequest, LoginRequest,LoginResponse
from app.core.logging import logger
router = APIRouter(tags=['auth'])

@router.post('/regiter')
async def register_user(request: RegisterRequest, db: AsyncSession = Depends(get_db)):
    pass
