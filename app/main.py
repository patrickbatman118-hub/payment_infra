# app/main.py
from fastapi import FastAPI
from app.core.exceptions import PaymentInfraException, payment_infra_exception_handler

app = FastAPI()


app.add_exception_handler(PaymentInfraException, payment_infra_exception_handler)
