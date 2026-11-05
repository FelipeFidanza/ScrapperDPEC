"""Los tests nunca acceden a la web de la DPEC: usan respuestas reales guardadas en fixtures/."""

import copy
import json
import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, make_url, text
from sqlmodel import Session, SQLModel

from scrapper_dpec.cliente import ClienteDPEC
from scrapper_dpec.config import normalizar_url_db
from scrapper_dpec.notifiers import ErrorNotificacion, Mensaje, Notifier

FIXTURES = Path(__file__).parent / "fixtures"
BACKEND = Path(__file__).parent.parent
BASE_URL = "https://dpec.test"


def leer_fixture(nombre: str) -> str:
    return (FIXTURES / nombre).read_text(encoding="utf-8")


def articulos_reales() -> list[dict]:
    return copy.deepcopy(json.loads(leer_fixture("articulos_pagina1.json")))


class NotifierFalso(Notifier):
    """Registra lo que se habría enviado. Con ``fallar=True`` simula un error del canal."""

    def __init__(self) -> None:
        self.enviados: list[tuple[str, Mensaje]] = []
        self.fallar = False

    def enviar(self, destino: str, mensaje: Mensaje) -> None:
        if self.fallar:
            raise ErrorNotificacion("canal caído")
        self.enviados.append((destino, mensaje))


@pytest.fixture
def notifier() -> NotifierFalso:
    return NotifierFalso()


@pytest.fixture
def cliente() -> Iterator[ClienteDPEC]:
    c = ClienteDPEC(BASE_URL, "tests", dormir=lambda _: None)
    yield c
    c.close()


def config_alembic(url: str) -> Config:
    config = Config(str(BACKEND / "alembic.ini"))
    config.attributes["url"] = url
    return config


@pytest.fixture(scope="session")
def url_test() -> str:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        if os.environ.get("CI"):
            pytest.fail("En CI los tests de base de datos no pueden omitirse.")
        pytest.skip("Definí TEST_DATABASE_URL para correr los tests de base de datos.")
    url = normalizar_url_db(url)
    # Estos tests borran todo: nunca deben apuntar a una base que no sea de pruebas.
    if not (make_url(url).database or "").endswith("_test"):
        pytest.fail("TEST_DATABASE_URL debe apuntar a una base cuyo nombre termine en _test.")
    return url


@pytest.fixture(scope="session")
def motor(url_test: str) -> Iterator[Engine]:
    engine = create_engine(url_test, connect_args={"connect_timeout": 15})
    with engine.begin() as conexion:
        conexion.execute(text("DROP SCHEMA public CASCADE"))
        conexion.execute(text("CREATE SCHEMA public"))
    command.upgrade(config_alembic(url_test), "head")
    yield engine
    engine.dispose()


@pytest.fixture
def sesion(motor: Engine) -> Iterator[Session]:
    with motor.begin() as conexion:
        for tabla in reversed(SQLModel.metadata.sorted_tables):
            conexion.execute(text(f"TRUNCATE {tabla.name} RESTART IDENTITY CASCADE"))
    with Session(motor) as session:
        yield session
