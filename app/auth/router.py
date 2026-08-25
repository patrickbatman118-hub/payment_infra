from fastapi import APIRouter, Depends
from app.auth.service  import register_user, login
from app.core.database import get_db, AsyncSession
from app.schemas.auth import RegisterRequest, LoginRequest,LoginResponse
from app.core.logging import logger
router = APIRouter(tags=['auth'])

@router.post('/regiter')
async def user_registration(request: RegisterRequest, db: AsyncSession = Depends(get_db)):
    logger.info(f'registering user {request.email}')
    return await register_user(db,request.email, request.password, request.name, request.phone)

@router.post('/login',response_model=LoginResponse)
async def login_user(request: LoginRequest, db: AsyncSession = Depends(get_db)):
    logger.info(f'login user {request.email}')
    return await login(db, request.email, request.password)

