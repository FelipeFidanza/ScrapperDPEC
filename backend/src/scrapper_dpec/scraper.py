"""Guarda en la base lo que publica la DPEC. No envía nada: de eso se ocupa ``notificador``."""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import delete, func
from sqlalchemy.dialects.postgresql import insert
from sqlmodel import Session

from scrapper_dpec.cliente import ArticuloDPEC, ClienteDPEC, ErrorFuenteDPEC
from scrapper_dpec.modelos import Corte, CorteDia, Zona
from scrapper_dpec.parser import CuerpoParseado, TituloParseado, parsear_cuerpo, parsear_titulo
from scrapper_dpec.texto import normalizar

log = logging.getLogger(__name__)

# Los avisos viejos no se van a notificar: no hace falta pedirle sus páginas a la DPEC.
ANTIGUEDAD_MAX_CUERPO = timedelta(days=30)


@dataclass
class ResultadoSync:
    nuevos: int = 0
    actualizados: int = 0
    errores_cuerpo: int = 0
    sin_fecha: list[int] = field(default_factory=list)

    @property
    def hay_problemas(self) -> bool:
        return bool(self.errores_cuerpo or self.sin_fecha)


def _registrar_zonas(session: Session, titulo: TituloParseado, publicado: datetime) -> None:
    vistas: set[tuple[str, str, str]] = set()
    for zona in titulo.zonas:
        clave = (normalizar(zona.nombre), zona.tipo, zona.localidad)
        if not clave[0] or clave in vistas:
            continue
        vistas.add(clave)
        insercion = insert(Zona).values(
            nombre=zona.nombre,
            nombre_norm=clave[0],
            tipo=zona.tipo,
            localidad_norm=zona.localidad,
            veces_vista=1,
            primera_vez=publicado,
            ultima_vez=publicado,
        )
        session.execute(
            insercion.on_conflict_do_update(
                index_elements=["nombre_norm", "tipo", "localidad_norm"],
                set_={
                    "veces_vista": Zona.veces_vista + 1,
                    "primera_vez": func.least(Zona.primera_vez, publicado),
                    "ultima_vez": func.greatest(Zona.ultima_vez, publicado),
                },
            )
        )


def _traer_cuerpo(
    cliente: ClienteDPEC, articulo: ArticuloDPEC, resultado: ResultadoSync
) -> CuerpoParseado | None:
    try:
        cuerpo = parsear_cuerpo(cliente.obtener_html(articulo.enlace))
    except ErrorFuenteDPEC as error:
        log.warning("Aviso %s: %s", articulo.articulo_id, error)
        resultado.errores_cuerpo += 1
        return None
    if cuerpo is None:
        log.warning("Aviso %s: la página cambió de estructura.", articulo.articulo_id)
        resultado.errores_cuerpo += 1
    return cuerpo


def registrar_articulo(
    session: Session,
    cliente: ClienteDPEC,
    articulo: ArticuloDPEC,
    momento: datetime,
    resultado: ResultadoSync,
    *,
    traer_cuerpos: bool = True,
) -> None:
    if not articulo.es_corte_publicado:
        return

    existente = session.get(Corte, articulo.articulo_id)
    es_nuevo = existente is None
    cambio = es_nuevo or existente.titulo != articulo.titulo
    reciente = momento - articulo.publicado_en <= ANTIGUEDAD_MAX_CUERPO
    falta_cuerpo = es_nuevo or existente.cuerpo is None
    pedir_cuerpo = traer_cuerpos and reciente and (cambio or falta_cuerpo)

    if not cambio and not pedir_cuerpo:
        existente.ultima_vez_visto = momento
        session.commit()
        return

    cuerpo = _traer_cuerpo(cliente, articulo, resultado) if pedir_cuerpo else None
    if not cambio and cuerpo is None:
        existente.ultima_vez_visto = momento
        session.commit()
        return

    titulo = parsear_titulo(articulo.titulo)
    fechas = titulo.fechas or (cuerpo.fechas if cuerpo else [])
    # El cuerpo manda: el título "De 08:13 y de 08:12" tenía el horario real solo en el cuerpo.
    franjas = (cuerpo.franjas if cuerpo else []) or titulo.franjas

    corte = existente or Corte(
        articulo_id=articulo.articulo_id,
        titulo=articulo.titulo,
        enlace=cliente.url_de(articulo.enlace),
        publicado_en=articulo.publicado_en,
        zona_texto=titulo.zona_texto,
        primera_vez_visto=momento,
        ultima_vez_visto=momento,
    )
    corte.titulo = articulo.titulo
    corte.enlace = cliente.url_de(articulo.enlace)
    corte.publicado_en = articulo.publicado_en
    corte.zona_texto = titulo.zona_texto
    corte.localidades = titulo.localidades
    corte.franjas = [franja.como_dict() for franja in franjas]
    corte.advertencias = titulo.advertencias
    corte.cuerpo = cuerpo.texto if cuerpo else None
    corte.cronograma = cuerpo.cronograma if cuerpo else None
    corte.datos_crudos = articulo.datos_crudos
    corte.ultima_vez_visto = momento
    session.add(corte)
    session.flush()

    session.execute(delete(CorteDia).where(CorteDia.articulo_id == corte.articulo_id))
    session.add_all(CorteDia(articulo_id=corte.articulo_id, fecha=fecha) for fecha in fechas)

    if es_nuevo:
        _registrar_zonas(session, titulo, articulo.publicado_en)
        resultado.nuevos += 1
    else:
        resultado.actualizados += 1
    session.commit()

    if es_nuevo and reciente and not fechas:
        log.warning("Aviso %s sin fecha interpretable.", articulo.articulo_id)
        resultado.sin_fecha.append(articulo.articulo_id)


def sincronizar(session: Session, cliente: ClienteDPEC, momento: datetime) -> ResultadoSync:
    resultado = ResultadoSync()
    for articulo in cliente.listar_recientes():
        registrar_articulo(session, cliente, articulo, momento, resultado)
    return resultado


def cargar_historico(
    session: Session,
    cliente: ClienteDPEC,
    momento: datetime,
    *,
    dormir: Callable[[float], None] = time.sleep,
) -> ResultadoSync:
    """Carga por única vez todos los títulos publicados, para arrancar con el catálogo de zonas."""
    resultado = ResultadoSync()
    pagina = 1
    vistos: set[int] = set()
    while True:
        articulos = [a for a in cliente.listar(pagina=pagina) if a.articulo_id not in vistos]
        if not articulos:
            return resultado
        for articulo in articulos:
            vistos.add(articulo.articulo_id)
            registrar_articulo(session, cliente, articulo, momento, resultado, traer_cuerpos=False)
        log.info("Página %s: %s avisos nuevos en total.", pagina, resultado.nuevos)
        pagina += 1
        dormir(1.0)  # Sin apuro: es una sola vez y el servidor no es nuestro.
