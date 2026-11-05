"""Comandos: ``dpec run``, ``dpec suscribir``, ``dpec cargar-historico``, ``dpec probar-email``.

``dpec run`` termina con código 1 si algo falló: GitHub marca el workflow como fallido y envía el
aviso por email. Los logs de Actions son públicos si el repo lo es, así que aquí nunca se imprimen
emails, palabras clave ni detalles de conexión.
"""

import argparse
import logging
import sys
from collections.abc import Callable
from datetime import datetime

from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, select

from scrapper_dpec.cliente import ClienteDPEC, ErrorFuenteDPEC
from scrapper_dpec.config import Settings, get_settings
from scrapper_dpec.db import get_engine
from scrapper_dpec.modelos import Suscripcion
from scrapper_dpec.notificador import notificar
from scrapper_dpec.notifiers import (
    CANAL_EMAIL,
    ErrorNotificacion,
    Mensaje,
    Notifier,
    crear_notifier,
)
from scrapper_dpec.scraper import cargar_historico, sincronizar
from scrapper_dpec.texto import normalizar
from scrapper_dpec.tiempo import ahora

log = logging.getLogger("scrapper_dpec")


def ejecutar(
    session: Session,
    cliente: ClienteDPEC,
    obtener_notifier: Callable[[str], Notifier],
    momento: datetime,
) -> bool:
    """Sincroniza y notifica. Devuelve ``True`` si todo salió bien.

    Si la DPEC no responde, igual se envían los avisos ya guardados: un fallo de la fuente no debe
    impedir avisar un corte que ya se conoce.
    """
    ok = True
    try:
        sync = sincronizar(session, cliente, momento)
        log.info(
            "Sincronización: %s nuevos, %s actualizados, %s cuerpos con error, %s sin fecha.",
            sync.nuevos,
            sync.actualizados,
            sync.errores_cuerpo,
            len(sync.sin_fecha),
        )
        ok = not sync.hay_problemas
    except ErrorFuenteDPEC as error:
        log.error("Fuente DPEC: %s", error)
        session.rollback()
        ok = False

    envio = notificar(session, obtener_notifier, momento)
    log.info("Notificaciones: %s enviadas, %s fallidas.", envio.enviadas, envio.fallidas)
    return ok and envio.fallidas == 0


def _obtener_notifier(settings: Settings) -> Callable[[str], Notifier]:
    creados: dict[str, Notifier] = {}

    def obtener(canal: str) -> Notifier:
        if canal not in creados:
            creados[canal] = crear_notifier(canal, settings)
        return creados[canal]

    return obtener


def _cliente(settings: Settings) -> ClienteDPEC:
    return ClienteDPEC(settings.dpec_base_url, settings.user_agent)


def _run(_: argparse.Namespace) -> int:
    settings = get_settings()
    cliente = _cliente(settings)
    try:
        with Session(get_engine()) as session:
            return 0 if ejecutar(session, cliente, _obtener_notifier(settings), ahora()) else 1
    except SQLAlchemyError as error:
        # Sin el mensaje original, que puede incluir host y usuario de la base.
        log.error("Error de base de datos: %s", type(error).__name__)
        return 1
    finally:
        cliente.close()


def _cargar_historico(_: argparse.Namespace) -> int:
    settings = get_settings()
    cliente = _cliente(settings)
    try:
        with Session(get_engine()) as session:
            resultado = cargar_historico(session, cliente, ahora())
    finally:
        cliente.close()
    print(f"Histórico cargado: {resultado.nuevos} avisos nuevos.")
    return 0


def _suscribir(args: argparse.Namespace) -> int:
    claves = [c.strip() for c in args.clave if normalizar(c)]
    if not claves:
        print("Hace falta al menos una palabra clave.", file=sys.stderr)
        return 2
    with Session(get_engine()) as session:
        existente = session.exec(
            select(Suscripcion).where(
                Suscripcion.canal == CANAL_EMAIL, Suscripcion.destino == args.email
            )
        ).first()
        suscripcion = existente or Suscripcion(
            nombre=args.nombre, canal=CANAL_EMAIL, destino=args.email, creada_en=ahora()
        )
        suscripcion.nombre = args.nombre
        suscripcion.palabras_clave = claves
        suscripcion.localidades_excluidas = args.excluir
        suscripcion.activa = True
        session.add(suscripcion)
        session.commit()
    print("Suscripción actualizada." if existente else "Suscripción creada.")
    return 0


def _probar_email(args: argparse.Namespace) -> int:
    notifier = crear_notifier(CANAL_EMAIL, get_settings())
    mensaje = Mensaje(
        asunto="Prueba de ScrapperDPEC",
        cuerpo="Si te llegó este mensaje, el envío de avisos por email funciona.",
    )
    try:
        notifier.enviar(args.para, mensaje)
    except ErrorNotificacion as error:
        print(error, file=sys.stderr)
        return 1
    print("Enviado.")
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    parser = argparse.ArgumentParser(prog="dpec", description=__doc__)
    comandos = parser.add_subparsers(required=True)

    comandos.add_parser("run", help="sincroniza con la DPEC y envía avisos").set_defaults(
        funcion=_run
    )
    comandos.add_parser(
        "cargar-historico", help="carga todos los títulos publicados (una sola vez)"
    ).set_defaults(funcion=_cargar_historico)

    suscribir = comandos.add_parser("suscribir", help="crea o actualiza una suscripción por email")
    suscribir.add_argument("--nombre", required=True)
    suscribir.add_argument("--email", required=True)
    suscribir.add_argument(
        "--clave", action="append", required=True, help="zona a buscar; se puede repetir"
    )
    suscribir.add_argument(
        "--excluir", action="append", default=[], help="localidad a ignorar; se puede repetir"
    )
    suscribir.set_defaults(funcion=_suscribir)

    probar = comandos.add_parser("probar-email", help="envía un email de prueba")
    probar.add_argument("--para", required=True)
    probar.set_defaults(funcion=_probar_email)

    args = parser.parse_args(argv)
    return args.funcion(args)


if __name__ == "__main__":
    sys.exit(main())
