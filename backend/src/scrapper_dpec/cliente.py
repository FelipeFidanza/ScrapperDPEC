"""Acceso a la web de la DPEC. Cualquier cambio en lo que devuelve termina en ErrorFuenteDPEC."""

import logging
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from scrapper_dpec.tiempo import ZONA_HORARIA

log = logging.getLogger(__name__)

SECCION_CORTES = 17
_ESPERAS_REINTENTO = (5.0, 15.0)


class ErrorFuenteDPEC(Exception):
    """La DPEC no responde o cambió el formato de lo que publica."""


class ArticuloDPEC(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    articulo_id: int = Field(alias="articuloId")
    titulo: str = Field(min_length=1)
    enlace: str
    publicado_en: datetime = Field(alias="fechaIso")
    activo: bool
    seccion_id: int = Field(alias="seccionId")
    estado: str
    datos_crudos: dict[str, Any] = Field(default_factory=dict, exclude=True)

    @field_validator("enlace")
    @classmethod
    def _enlace_interno(cls, valor: str) -> str:
        # Solo se visitan páginas de la DPEC, aunque la respuesta dijera otra cosa.
        if not valor.startswith("/") or valor.startswith("//"):
            raise ValueError("el enlace no es una ruta interna")
        return valor

    @field_validator("publicado_en")
    @classmethod
    def _con_zona_horaria(cls, valor: datetime) -> datetime:
        return valor if valor.tzinfo else valor.replace(tzinfo=ZONA_HORARIA)

    @property
    def es_corte_publicado(self) -> bool:
        return self.activo and self.seccion_id == SECCION_CORTES and self.estado == "Publicado"


class ClienteDPEC:
    def __init__(
        self,
        base_url: str,
        user_agent: str,
        *,
        dormir: Callable[[float], None] = time.sleep,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._dormir = dormir
        self._http = httpx.Client(
            base_url=self.base_url,
            headers={"User-Agent": user_agent},
            timeout=30.0,
            follow_redirects=True,
        )

    def close(self) -> None:
        self._http.close()

    def _get(self, ruta: str, **kwargs: Any) -> httpx.Response:
        ultimo_error = "sin intentos"
        for intento in range(len(_ESPERAS_REINTENTO) + 1):
            if intento:
                self._dormir(_ESPERAS_REINTENTO[intento - 1])
            try:
                respuesta = self._http.get(ruta, **kwargs)
            except httpx.TransportError as error:
                ultimo_error = type(error).__name__
                continue
            if respuesta.status_code == 200:
                return respuesta
            ultimo_error = f"HTTP {respuesta.status_code}"
            if respuesta.status_code < 500 and respuesta.status_code != 429:
                break  # Un 404 no se arregla reintentando.
        raise ErrorFuenteDPEC(f"GET {ruta} falló: {ultimo_error}")

    def listar(self, pagina: int = 1, filas: int = 50) -> list[ArticuloDPEC]:
        respuesta = self._get(
            f"/es/seccion/{SECCION_CORTES}-articulos.json",
            params={"rows": filas, "page": pagina},
            headers={"Accept": "application/json"},
        )
        try:
            datos = respuesta.json()
            if not isinstance(datos, list):
                raise ValueError("se esperaba una lista")
            articulos = []
            for crudo in datos:
                articulo = ArticuloDPEC.model_validate(crudo)
                articulo.datos_crudos = crudo
                articulos.append(articulo)
            return articulos
        except (ValueError, ValidationError) as error:
            raise ErrorFuenteDPEC(f"Cambió el formato de la lista de cortes: {error}") from error

    def listar_recientes(self) -> list[ArticuloDPEC]:
        articulos = self.listar()
        if not articulos:
            # La sección siempre conserva avisos viejos: vacía indica que algo se rompió.
            raise ErrorFuenteDPEC("La lista de cortes vino vacía.")
        return articulos

    def obtener_html(self, enlace: str) -> str:
        return self._get(enlace).text

    def url_de(self, enlace: str) -> str:
        return f"{self.base_url}{enlace}"
