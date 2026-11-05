"""API de solo lectura, pensada para el futuro frontend (calendario y catálogo de zonas).

Todavía no se despliega. No expone suscripciones: contienen datos personales, y darse de alta
públicamente va a requerir verificar el email antes.
"""

from datetime import date, timedelta
from typing import Annotated

from fastapi import Depends, FastAPI, Query
from pydantic import BaseModel
from sqlmodel import Session, select

from scrapper_dpec.db import get_session
from scrapper_dpec.modelos import Corte, CorteDia, Zona
from scrapper_dpec.tiempo import ahora

app = FastAPI(title="ScrapperDPEC", version="0.1.0")
SesionDB = Annotated[Session, Depends(get_session)]


class CorteDelDia(BaseModel):
    fecha: date
    articulo_id: int
    titulo: str
    zona: str
    franjas: list[dict[str, str]]
    enlace: str


class ZonaCatalogo(BaseModel):
    nombre: str
    tipo: str
    veces_vista: int


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/cortes")
def listar_cortes(
    session: SesionDB, desde: date | None = None, hasta: date | None = None
) -> list[CorteDelDia]:
    inicio = desde or ahora().date()
    fin = hasta or inicio + timedelta(days=30)
    filas = session.exec(
        select(Corte, CorteDia.fecha)
        .join(CorteDia, CorteDia.articulo_id == Corte.articulo_id)
        .where(CorteDia.fecha >= inicio, CorteDia.fecha <= fin)
        .order_by(CorteDia.fecha, Corte.articulo_id)
    ).all()
    return [
        CorteDelDia(
            fecha=fecha,
            articulo_id=corte.articulo_id,
            titulo=corte.titulo,
            zona=corte.zona_texto,
            franjas=corte.franjas,
            enlace=corte.enlace,
        )
        for corte, fecha in filas
    ]


@app.get("/zonas")
def listar_zonas(
    session: SesionDB,
    tipo: str = "localidad",
    limite: Annotated[int, Query(ge=1, le=500)] = 200,
) -> list[ZonaCatalogo]:
    zonas = session.exec(
        select(Zona)
        .where(Zona.tipo == tipo)
        .order_by(Zona.veces_vista.desc(), Zona.nombre)
        .limit(limite)
    ).all()
    return [ZonaCatalogo(nombre=z.nombre, tipo=z.tipo, veces_vista=z.veces_vista) for z in zonas]
