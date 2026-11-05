"""Tablas de la base de datos."""

from datetime import date, datetime
from typing import Any

from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel


def _momento(**kwargs: Any) -> Any:
    return Field(sa_column=Column(DateTime(timezone=True), nullable=False, **kwargs))


def _json() -> Any:
    return Field(default_factory=list, sa_column=Column(JSONB, nullable=False))


class Corte(SQLModel, table=True):
    """Un aviso de la DPEC. Puede abarcar varios días (ver ``CorteDia``)."""

    __tablename__ = "cortes"

    articulo_id: int = Field(sa_column=Column(Integer, primary_key=True, autoincrement=False))
    titulo: str
    enlace: str
    publicado_en: datetime = _momento()
    zona_texto: str
    localidades: list[str] = _json()
    franjas: list[dict[str, str]] = _json()
    advertencias: list[str] = _json()
    cuerpo: str | None = None
    cronograma: str | None = None
    datos_crudos: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSONB, nullable=False)
    )
    primera_vez_visto: datetime = _momento()
    ultima_vez_visto: datetime = _momento()


class CorteDia(SQLModel, table=True):
    """Cada día afectado por un aviso: es lo que permite armar el calendario."""

    __tablename__ = "corte_dias"

    articulo_id: int = Field(
        sa_column=Column(
            Integer, ForeignKey("cortes.articulo_id", ondelete="CASCADE"), primary_key=True
        )
    )
    fecha: date = Field(sa_column=Column(Date, primary_key=True, index=True))


class Zona(SQLModel, table=True):
    """Catálogo de lugares mencionados en los avisos, base de una futura lista de suscripción."""

    __tablename__ = "zonas"
    __table_args__ = (UniqueConstraint("nombre_norm", "tipo", "localidad_norm"),)

    id: int | None = Field(default=None, primary_key=True)
    nombre: str
    nombre_norm: str
    tipo: str
    localidad_norm: str = ""
    veces_vista: int = 1
    primera_vez: datetime = _momento()
    ultima_vez: datetime = _momento()


class Suscripcion(SQLModel, table=True):
    __tablename__ = "suscripciones"
    __table_args__ = (UniqueConstraint("canal", "destino"),)

    id: int | None = Field(default=None, primary_key=True)
    nombre: str
    canal: str
    destino: str
    palabras_clave: list[str] = _json()
    localidades_excluidas: list[str] = _json()
    activa: bool = True
    creada_en: datetime = _momento()


class Notificacion(SQLModel, table=True):
    """Registro de lo enviado: garantiza que cada día de cada corte se avise una sola vez."""

    __tablename__ = "notificaciones"

    suscripcion_id: int = Field(
        sa_column=Column(
            Integer, ForeignKey("suscripciones.id", ondelete="CASCADE"), primary_key=True
        )
    )
    articulo_id: int = Field(
        sa_column=Column(
            Integer, ForeignKey("cortes.articulo_id", ondelete="CASCADE"), primary_key=True
        )
    )
    fecha: date = Field(sa_column=Column(Date, primary_key=True))
    enviada_en: datetime = _momento()
