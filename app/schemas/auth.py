from pydantic import BaseModel, Field, EmailStr, model_validator, ValidationError


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=100)
    confirm_password: str = Field(min_length=8, max_length=100)
    name: str | None = None
    phone: str | None = None

    @model_validator(mode='after')
    def check_pass(self):
        if self.password != self.confirm_password:
            raise ValidationError('Passwords do not match')
        return self

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class LoginResponse(BaseModel):
    access_token: str
    token_type: str

    class Config:
        from_attributes = True