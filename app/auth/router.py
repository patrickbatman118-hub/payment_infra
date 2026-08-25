from fastapi import APIRouter, Depends
from app.auth.service  import register_user, login
from app.core.database import get_db, AsyncSession
from app.schemas.auth import RegisterRequest, LoginRequest,LoginResponse
from app.core.logging import logger
router = APIRouter(tags=['auth'])

@router.post('/register')
async def user_registration(request: RegisterRequest, db: AsyncSession = Depends(get_db)):
    logger.info(f'user registration request ')
    return await register_user(db,request.email, request.password, request.name, request.phone)

@router.post('/login',response_model=LoginResponse)
async def login_user(request: LoginRequest, db: AsyncSession = Depends(get_db)):
    logger.info(f'user login request ')
    return await login(db, request.email, request.password)

