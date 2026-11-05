"""Configuración leída de variables de entorno o de backend/.env."""

from functools import lru_cache

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def normalizar_url_db(url: str) -> str:
    """Supabase entrega 'postgresql://...'; SQLAlchemy necesita que se indique el driver."""
    for prefijo in ("postgresql://", "postgres://"):
        if url.startswith(prefijo):
            return "postgresql+psycopg://" + url.removeprefix(prefijo)
    return url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = ""
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: SecretStr = SecretStr("")

    dpec_base_url: str = "https://www.dpec.com.ar"
    user_agent: str = "ScrapperDPEC/0.1 (proyecto personal de avisos de cortes programados)"

    @field_validator("database_url")
    @classmethod
    def _url_con_driver(cls, valor: str) -> str:
        return normalizar_url_db(valor.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()
