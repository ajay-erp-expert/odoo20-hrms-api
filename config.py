from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    odoo_url: str = "http://localhost:8069"
    odoo_db: str = "odoo20.0_db"
    odoo_api_key: str
    odoo_timeout: float = 30.0

    model_config = SettingsConfigDict(
        env_file=Path(__file__).parent / ".env",
        extra="ignore",
    )


settings = Settings()
