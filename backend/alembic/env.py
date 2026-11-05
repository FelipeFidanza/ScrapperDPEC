"""Migraciones. La URL se pasa al motor directamente: las contraseñas pueden tener '%'."""

from alembic import context
from sqlalchemy import create_engine
from sqlmodel import SQLModel

from scrapper_dpec import modelos  # noqa: F401  (registra las tablas en los metadatos)
from scrapper_dpec.config import get_settings, normalizar_url_db

url = context.config.attributes.get("url") or get_settings().database_url
if not url:
    raise RuntimeError("Falta la variable DATABASE_URL (ver backend/.env.example).")

motor = create_engine(normalizar_url_db(url), connect_args={"connect_timeout": 15})
with motor.connect() as conexion:
    context.configure(connection=conexion, target_metadata=SQLModel.metadata)
    with context.begin_transaction():
        context.run_migrations()
motor.dispose()
