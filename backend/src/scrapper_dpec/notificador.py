"""Cruza los cortes guardados con las suscripciones y envía los avisos pendientes."""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlmodel import Session, select

from scrapper_dpec.modelos import Corte, CorteDia, Notificacion, Suscripcion
from scrapper_dpec.notifiers import ErrorNotificacion, Mensaje, Notifier
from scrapper_dpec.texto import contiene_frase, normalizar

log = logging.getLogger(__name__)

_DIAS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
# Un aviso sin fecha se avisa igual, pero solo si es reciente.
_ANTIGUEDAD_MAX_SIN_FECHA = timedelta(days=7)


@dataclass
class ResultadoNotificacion:
    enviadas: int = 0
    fallidas: int = 0


def palabra_que_coincide(suscripcion: Suscripcion, corte: Corte) -> str | None:
    """Devuelve la palabra clave encontrada en el título o el cuerpo del aviso, si hay alguna.

    "Santa Teresita" existe en varias ciudades, así que se puede excluir localidades. Solo se
    descarta un aviso si *todas* sus localidades están excluidas: ante la duda, se avisa. Se
    comparan las localidades y no el texto, porque Capital también tiene un B° Bella Vista.
    """
    excluidas = {normalizar(x) for x in suscripcion.localidades_excluidas}
    if corte.localidades and all(loc in excluidas for loc in corte.localidades):
        return None
    texto = normalizar(f"{corte.titulo}\n{corte.cuerpo or ''}")
    for palabra in suscripcion.palabras_clave:
        if contiene_frase(texto, normalizar(palabra)):
            return palabra
    return None


def _ya_termino(corte: Corte, momento: datetime) -> bool:
    """Si no se conoce el horario, se asume que no terminó."""
    if not corte.franjas:
        return False
    return momento.strftime("%H:%M") >= max(franja["hasta"] for franja in corte.franjas)


def _describir_horario(corte: Corte) -> str:
    if not corte.franjas:
        return "no se pudo determinar (ver el aviso)"
    horarios = " / ".join(f"{f['desde']} a {f['hasta']}" for f in corte.franjas)
    return f"{horarios} (según la zona, ver detalle)" if len(corte.franjas) > 1 else horarios


def construir_mensaje(
    suscripcion: Suscripcion, corte: Corte, fecha: date | None, hoy: date, palabra: str
) -> Mensaje:
    zona = corte.zona_texto or corte.titulo
    if fecha is None:
        asunto = f"Aviso de corte de la DPEC sin fecha clara: {zona}"
        cuando = "no se pudo determinar la fecha (revisá el aviso)"
    else:
        dia = f"{_DIAS[fecha.weekday()]} {fecha:%d/%m}"
        relativo = "HOY" if fecha == hoy else "MAÑANA"
        asunto = f"Corte de luz {relativo}, {dia}: {zona}"
        cuando = f"{relativo.lower()}, {_DIAS[fecha.weekday()]} {fecha:%d/%m/%Y}"
    if len(asunto) > 120:
        asunto = asunto[:117] + "..."

    lineas = [
        f"Hola, {suscripcion.nombre}:",
        "",
        f'La DPEC publicó un corte programado que coincide con tu zona ("{palabra}").',
        "",
        f"Cuándo: {cuando}",
        f"Horario: {_describir_horario(corte)}",
        f"Aviso: {corte.titulo}",
    ]
    inconsistencias = [a for a in corte.advertencias if a.startswith("el día no coincide")]
    if inconsistencias:
        lineas += ["", f"Atención, el aviso parece tener un error: {inconsistencias[0]}."]
    if corte.cronograma:
        lineas += ["", "Detalle publicado:", corte.cronograma]
    lineas += [
        "",
        f"Ver el aviso oficial: {corte.enlace}",
        "",
        "--",
        "Mensaje automático de ScrapperDPEC, un proyecto personal sin relación con la DPEC.",
    ]
    return Mensaje(asunto=asunto, cuerpo="\n".join(lineas))


def _pendientes(session: Session, momento: datetime) -> list[tuple[Corte, date | None]]:
    """Cortes de hoy (si no terminaron) y de mañana, más los avisos recientes sin fecha."""
    hoy = momento.date()
    fechados = session.exec(
        select(Corte, CorteDia.fecha)
        .join(CorteDia, CorteDia.articulo_id == Corte.articulo_id)
        .where(CorteDia.fecha.in_([hoy, hoy + timedelta(days=1)]))
        .order_by(CorteDia.fecha, Corte.articulo_id)
    ).all()
    pendientes: list[tuple[Corte, date | None]] = [
        (corte, fecha)
        for corte, fecha in fechados
        if fecha != hoy or not _ya_termino(corte, momento)
    ]
    sin_fecha = session.exec(
        select(Corte)
        .where(Corte.publicado_en >= momento - _ANTIGUEDAD_MAX_SIN_FECHA)
        .where(~Corte.articulo_id.in_(select(CorteDia.articulo_id)))
        .order_by(Corte.articulo_id)
    ).all()
    pendientes.extend((corte, None) for corte in sin_fecha)
    return pendientes


def notificar(
    session: Session,
    obtener_notifier: Callable[[str], Notifier],
    momento: datetime,
) -> ResultadoNotificacion:
    resultado = ResultadoNotificacion()
    hoy = momento.date()
    suscripciones = session.exec(select(Suscripcion).where(Suscripcion.activa)).all()
    pendientes = _pendientes(session, momento)

    for suscripcion in suscripciones:
        for corte, fecha in pendientes:
            palabra = palabra_que_coincide(suscripcion, corte)
            if palabra is None:
                continue
            # Los avisos sin fecha se registran con la fecha de publicación.
            fecha_clave = fecha or corte.publicado_en.astimezone(momento.tzinfo).date()
            clave = (suscripcion.id, corte.articulo_id, fecha_clave)
            if session.get(Notificacion, clave):
                continue
            mensaje = construir_mensaje(suscripcion, corte, fecha, hoy, palabra)
            try:
                obtener_notifier(suscripcion.canal).enviar(suscripcion.destino, mensaje)
            except ErrorNotificacion as error:
                # Sin registro: se reintenta en la próxima ejecución. Es preferible un aviso
                # repetido a uno perdido. Los logs de Actions son públicos: nada de destinos.
                log.error("Suscripción %s, aviso %s: %s", suscripcion.id, corte.articulo_id, error)
                resultado.fallidas += 1
                continue
            session.add(
                Notificacion(
                    suscripcion_id=suscripcion.id,
                    articulo_id=corte.articulo_id,
                    fecha=fecha_clave,
                    enviada_en=momento,
                )
            )
            session.commit()
            resultado.enviadas += 1
    return resultado
