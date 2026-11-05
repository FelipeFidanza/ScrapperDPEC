"""Conexión a PostgreSQL."""

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine
from sqlmodel import Session, create_engine

from scrapper_dpec.config import get_settings


@lru_cache
def get_engine() -> Engine:
    url = get_settings().database_url
    if not url:
        raise RuntimeError("Falta la variable DATABASE_URL (ver backend/.env.example).")
    # Con timeout: una base caída debe fallar rápido y avisar, no dejar colgado el workflow.
    return create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 15})


def get_session() -> Iterator[Session]:
    with Session(get_engine()) as session:
        yield session
