# app/main.py
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from app.core.exceptions import PaymentInfraException, payment_infra_exception_handler
from app.core.logging import logger
from app.payments import router
app = FastAPI()
app.include_router(router.router)

app.add_exception_handler(PaymentInfraException, payment_infra_exception_handler)
@app.exception_handler(Exception)
async def unhandled_exception_handler(request, exc):
    logger.error(f"Unhandled error: {exc}")
    return JSONResponse(status_code=500, content={"message": "Internal server error"})