from pydantic_settings import BaseSettings, SettingsConfigDict
import uuid
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', case_sensitive=False, extra="ignore")

    database_url: str
    secret_key: str
    algorithm: str = 'HS256'
    access_token_expire_minutes: int = 15
    environment: str 
    platform_account_id: uuid.UUID = uuid.UUID('123e4567-e89b-12d3-a456-426614174000')

settings = Settings()