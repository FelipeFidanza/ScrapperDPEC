"""Flujo completo contra PostgreSQL real: DPEC simulada -> base -> aviso."""

import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
import pytest
import respx
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlmodel import Session, select

from conftest import BASE_URL, NotifierFalso, articulos_reales, config_alembic, leer_fixture
from scrapper_dpec.api import app
from scrapper_dpec.cli import ejecutar
from scrapper_dpec.cliente import ClienteDPEC
from scrapper_dpec.db import get_session
from scrapper_dpec.modelos import Corte, CorteDia, Notificacion, Suscripcion, Zona
from scrapper_dpec.notificador import notificar
from scrapper_dpec.scraper import cargar_historico, sincronizar
from scrapper_dpec.tiempo import ZONA_HORARIA

pytestmark = pytest.mark.db

LISTA = f"{BASE_URL}/es/seccion/17-articulos.json"
# 4/11/2026 a las 20:00 en Corrientes: 8871 y 8870 son de mañana, 8866 de hoy a la semana próxima.
ANOCHECER = datetime(2026, 11, 4, 20, 0, tzinfo=ZONA_HORARIA)


CUERPO_NEUTRO = '<section class="articulo-contenido"><p>Se realizarán tareas.</p></section>'


def _simular_dpec(articulos: list[dict] | None = None) -> respx.Route:
    """Solo el aviso 8871 tiene su cuerpo real: el de los demás no agrega zonas ni horarios."""
    # respx usa la primera ruta que coincide: la específica va antes que la genérica.
    respx.get(url__regex=rf"^{BASE_URL}/8871/.*").mock(
        return_value=httpx.Response(200, text=leer_fixture("articulo_8871.html"))
    )
    respx.get(url__regex=rf"^{BASE_URL}/\d+/.*").mock(
        return_value=httpx.Response(200, text=CUERPO_NEUTRO)
    )
    return respx.get(LISTA).mock(
        return_value=httpx.Response(
            200, json=articulos_reales() if articulos is None else articulos
        )
    )


def _articulo(id_: int, titulo: str, publicado: str = "2026-11-04T10:00:00") -> dict:
    return {
        **articulos_reales()[0],
        "articuloId": str(id_),
        "titulo": titulo,
        "enlace": f"/{id_}/aviso",
        "fechaIso": publicado,
    }


def _suscribir(
    sesion: Session,
    claves: list[str],
    excluidas: list[str] | None = None,
    destino: str = "ana@x.test",
) -> Suscripcion:
    sub = Suscripcion(
        nombre="Ana",
        canal="email",
        destino=destino,
        palabras_clave=claves,
        localidades_excluidas=excluidas or [],
        creada_en=ANOCHECER,
    )
    sesion.add(sub)
    sesion.commit()
    return sub


def _obtener(notifier: NotifierFalso):
    return lambda _canal: notifier


@respx.mock
def test_sincronizar_guarda_los_avisos_reales(sesion: Session, cliente: ClienteDPEC) -> None:
    _simular_dpec()
    resultado = sincronizar(sesion, cliente, ANOCHECER)
    assert resultado.nuevos == 15
    assert not resultado.hay_problemas

    corte = sesion.get(Corte, 8871)
    assert corte.localidades == ["san roque", "bella vista"]
    assert corte.franjas == [{"desde": "07:00", "hasta": "08:30"}]
    assert corte.enlace.startswith(f"{BASE_URL}/8871/")
    assert corte.cuerpo and "HORARIO" in corte.cuerpo
    assert corte.datos_crudos["seccionId"] == 17


@respx.mock
def test_aviso_de_varios_dias_genera_un_dia_por_fecha(
    sesion: Session, cliente: ClienteDPEC
) -> None:
    _simular_dpec()
    sincronizar(sesion, cliente, ANOCHECER)
    dias = sesion.exec(select(CorteDia.fecha).where(CorteDia.articulo_id == 8866)).all()
    assert sorted(dias) == [date(2026, 11, 4) + timedelta(days=i) for i in range(7)]


@respx.mock
def test_segunda_sincronizacion_no_duplica_ni_repite_pedidos(
    sesion: Session, cliente: ClienteDPEC
) -> None:
    _simular_dpec()
    sincronizar(sesion, cliente, ANOCHECER)
    pedidos_cuerpo = sum(1 for c in respx.calls if "/es/seccion/" not in str(c.request.url))
    assert pedidos_cuerpo == 3  # Solo los recientes: los de 2023 no se piden.
    veces = sesion.exec(select(Zona.veces_vista).where(Zona.nombre == "Mercedes")).one()

    resultado = sincronizar(sesion, cliente, ANOCHECER + timedelta(hours=3))
    assert (resultado.nuevos, resultado.actualizados) == (0, 0)
    assert sum(1 for c in respx.calls if "/es/seccion/" not in str(c.request.url)) == pedidos_cuerpo
    sesion.expire_all()
    assert sesion.exec(select(Zona.veces_vista).where(Zona.nombre == "Mercedes")).one() == veces


@respx.mock
def test_titulo_corregido_actualiza_las_fechas(sesion: Session, cliente: ClienteDPEC) -> None:
    aviso = _articulo(9000, "VIERNES 06/11/26 | 08:00 a 10:00 h | GOYA")
    _simular_dpec([aviso])
    sincronizar(sesion, cliente, ANOCHECER)
    _simular_dpec([{**aviso, "titulo": "LUNES 09/11/26 | 08:00 a 10:00 h | GOYA"}])
    assert sincronizar(sesion, cliente, ANOCHECER).actualizados == 1
    dias = sesion.exec(select(CorteDia.fecha).where(CorteDia.articulo_id == 9000)).all()
    assert dias == [date(2026, 11, 9)]


@respx.mock
def test_avisa_una_sola_vez_lo_de_manana(
    sesion: Session, cliente: ClienteDPEC, notifier: NotifierFalso
) -> None:
    _simular_dpec()
    _suscribir(sesion, ["San Roque"])
    sincronizar(sesion, cliente, ANOCHECER)

    assert notificar(sesion, _obtener(notifier), ANOCHECER).enviadas == 1
    destino, mensaje = notifier.enviados[0]
    assert destino == "ana@x.test"
    assert "MAÑANA, jueves 05/11" in mensaje.asunto
    assert "07:00 a 08:30" in mensaje.cuerpo
    assert "/8871/" in mensaje.cuerpo
    assert "sin relación con la DPEC" in mensaje.cuerpo

    assert notificar(sesion, _obtener(notifier), ANOCHECER + timedelta(hours=3)).enviadas == 0


@respx.mock
def test_no_avisa_antes_de_tiempo(
    sesion: Session, cliente: ClienteDPEC, notifier: NotifierFalso
) -> None:
    _simular_dpec([_articulo(9001, "SÁBADO 07/11/26 | 08:00 a 10:00 h | GOYA")])
    _suscribir(sesion, ["Goya"])
    sincronizar(sesion, cliente, ANOCHECER)
    assert notificar(sesion, _obtener(notifier), ANOCHECER).enviadas == 0  # Faltan tres días.
    viernes = datetime(2026, 11, 6, 9, 0, tzinfo=ZONA_HORARIA)
    assert notificar(sesion, _obtener(notifier), viernes).enviadas == 1


@respx.mock
def test_manana_se_calcula_en_hora_de_corrientes(
    sesion: Session, cliente: ClienteDPEC, notifier: NotifierFalso
) -> None:
    """El runner está en UTC: a las 22:30 del 4/11 en Corrientes ya es 5/11 en UTC."""
    _simular_dpec(
        [
            _articulo(9002, "SÁBADO 07/11/26 | 08:00 a 10:00 h | GOYA"),
            _articulo(9003, "JUEVES 05/11/26 | 08:00 a 10:00 h | ITATÍ"),
        ]
    )
    _suscribir(sesion, ["Goya", "Itatí"])
    noche_utc = datetime(2026, 11, 5, 1, 30, tzinfo=ZoneInfo("UTC"))
    momento = noche_utc.astimezone(ZONA_HORARIA)
    assert momento.date() == date(2026, 11, 4)
    sincronizar(sesion, cliente, momento)
    notificar(sesion, _obtener(notifier), momento)
    assert [m.asunto for _, m in notifier.enviados] == ["Corte de luz MAÑANA, jueves 05/11: ITATÍ"]


@respx.mock
def test_corte_de_hoy_se_avisa_solo_si_no_termino(
    sesion: Session, cliente: ClienteDPEC, notifier: NotifierFalso
) -> None:
    _simular_dpec([_articulo(9004, "MIÉRCOLES 04/11/26 | 14:00 a 16:00 h | GOYA")])
    _suscribir(sesion, ["Goya"])
    sincronizar(sesion, cliente, ANOCHECER)
    assert notificar(sesion, _obtener(notifier), ANOCHECER).enviadas == 0  # Terminó a las 16.
    mediodia = ANOCHECER.replace(hour=12)
    assert notificar(sesion, _obtener(notifier), mediodia).enviadas == 1
    assert "HOY" in notifier.enviados[0][1].asunto


@respx.mock
def test_aviso_de_varios_dias_se_avisa_cada_dia(
    sesion: Session, cliente: ClienteDPEC, notifier: NotifierFalso
) -> None:
    _simular_dpec([_articulo(9005, "JUEVES 05, VIERNES 06/11/26 | 08:00 a 10:00 h | GOYA")])
    _suscribir(sesion, ["Goya"])
    sincronizar(sesion, cliente, ANOCHECER)
    assert notificar(sesion, _obtener(notifier), ANOCHECER).enviadas == 1  # Mañana.
    jueves_noche = ANOCHECER + timedelta(days=1)
    assert notificar(sesion, _obtener(notifier), jueves_noche).enviadas == 1  # El viernes.
    assert sesion.exec(select(Notificacion)).all().__len__() == 2


@respx.mock
def test_zona_que_solo_esta_en_el_cuerpo_se_avisa_con_el_horario_real(
    sesion: Session, cliente: ClienteDPEC, notifier: NotifierFalso
) -> None:
    aviso = _articulo(8679, "JUEVES 05/11/26 | De 08:13 y de 08:12 | CAPITAL  (Ver zonas)")
    respx.get(LISTA).mock(return_value=httpx.Response(200, json=[aviso]))
    respx.get(f"{BASE_URL}/8679/aviso").mock(
        return_value=httpx.Response(200, text=leer_fixture("articulo_8679_ver_zonas.html"))
    )
    _suscribir(sesion, ["Perichón"])
    sincronizar(sesion, cliente, ANOCHECER)
    notificar(sesion, _obtener(notifier), ANOCHECER)
    cuerpo = notifier.enviados[0][1].cuerpo
    assert "08:00 a 13:00 / 08:00 a 12:00" in cuerpo
    assert "Camping" in cuerpo


@respx.mock
def test_si_falla_el_envio_se_reintenta_en_la_proxima_ejecucion(
    sesion: Session, cliente: ClienteDPEC, notifier: NotifierFalso
) -> None:
    _simular_dpec()
    _suscribir(sesion, ["San Roque"])
    sincronizar(sesion, cliente, ANOCHECER)
    notifier.fallar = True
    assert notificar(sesion, _obtener(notifier), ANOCHECER).fallidas == 1
    assert not sesion.exec(select(Notificacion)).all()
    notifier.fallar = False
    assert notificar(sesion, _obtener(notifier), ANOCHECER).enviadas == 1


@respx.mock
def test_aviso_sin_fecha_se_avisa_una_vez_y_marca_el_problema(
    sesion: Session, cliente: ClienteDPEC, notifier: NotifierFalso
) -> None:
    _simular_dpec([_articulo(9006, "Cortes Programados Suspendidos para: Goya y Loreto")])
    _suscribir(sesion, ["Goya"])
    assert sincronizar(sesion, cliente, ANOCHECER).sin_fecha == [9006]
    assert notificar(sesion, _obtener(notifier), ANOCHECER).enviadas == 1
    assert "sin fecha clara" in notifier.enviados[0][1].asunto
    assert notificar(sesion, _obtener(notifier), ANOCHECER).enviadas == 0


@respx.mock
def test_titulo_sin_fecha_usa_la_del_cuerpo(sesion: Session, cliente: ClienteDPEC) -> None:
    # El cuerpo real del aviso 8871 dice "FECHA: JUEVES 05/11/26".
    _simular_dpec([_articulo(8871, "Aviso importante para SAN ROQUE")])
    assert sincronizar(sesion, cliente, ANOCHECER).sin_fecha == []
    dias = sesion.exec(select(CorteDia.fecha).where(CorteDia.articulo_id == 8871)).all()
    assert dias == [date(2026, 11, 5)]


@respx.mock
def test_suscripcion_inactiva_no_recibe(
    sesion: Session, cliente: ClienteDPEC, notifier: NotifierFalso
) -> None:
    _simular_dpec()
    sub = _suscribir(sesion, ["San Roque"])
    sub.activa = False
    sesion.commit()
    sincronizar(sesion, cliente, ANOCHECER)
    assert notificar(sesion, _obtener(notifier), ANOCHECER).enviadas == 0


@respx.mock
def test_si_la_dpec_esta_caida_igual_avisa_lo_ya_conocido(
    sesion: Session, cliente: ClienteDPEC, notifier: NotifierFalso
) -> None:
    _simular_dpec()
    sincronizar(sesion, cliente, ANOCHECER)
    _suscribir(sesion, ["San Roque"])
    respx.get(LISTA).mock(return_value=httpx.Response(503))
    assert ejecutar(sesion, cliente, _obtener(notifier), ANOCHECER) is False  # Workflow fallido.
    assert len(notifier.enviados) == 1


@respx.mock
def test_pagina_rediseniada_marca_problema_sin_perder_el_aviso(
    sesion: Session, cliente: ClienteDPEC, notifier: NotifierFalso
) -> None:
    respx.get(LISTA).mock(
        return_value=httpx.Response(
            200, json=[_articulo(9008, "JUEVES 05/11/26 | 08:00 a 10:00 h | GOYA")]
        )
    )
    respx.get(f"{BASE_URL}/9008/aviso").mock(return_value=httpx.Response(200, text="<html></html>"))
    _suscribir(sesion, ["Goya"])
    assert ejecutar(sesion, cliente, _obtener(notifier), ANOCHECER) is False
    assert len(notifier.enviados) == 1


@respx.mock
def test_ejecucion_correcta_y_logs_sin_datos_personales(
    sesion: Session, cliente: ClienteDPEC, notifier: NotifierFalso, caplog: pytest.LogCaptureFixture
) -> None:
    _simular_dpec()
    _suscribir(sesion, ["San Roque"], destino="privado@x.test")
    with caplog.at_level(logging.INFO):
        assert ejecutar(sesion, cliente, _obtener(notifier), ANOCHECER) is True
        notifier.fallar = True
        notificar(sesion, _obtener(notifier), ANOCHECER)
    assert "privado@x.test" not in caplog.text
    assert "San Roque" not in caplog.text


@respx.mock
def test_historico_recorre_paginas_sin_pedir_cuerpos(sesion: Session, cliente: ClienteDPEC) -> None:
    pagina1 = [_articulo(1, "MARTES 25/07/23 | 8 a 9 Hs. | GOYA", "2023-07-24T12:00:00")]
    pagina2 = [
        _articulo(2, "MIÉRCOLES 26/07/23 | 8 a 9 Hs. | GOYA y LORETO", "2023-07-25T12:00:00")
    ]
    ruta = respx.get(LISTA).mock(
        side_effect=[
            httpx.Response(200, json=pagina1),
            httpx.Response(200, json=pagina2),
            httpx.Response(200, json=[]),
        ]
    )
    pausas: list[float] = []
    resultado = cargar_historico(sesion, cliente, ANOCHECER, dormir=pausas.append)
    assert resultado.nuevos == 2
    assert ruta.call_count == 3
    assert len(pausas) == 2
    goya = sesion.exec(select(Zona).where(Zona.nombre == "Goya")).one()
    assert goya.veces_vista == 2


def test_api_calendario_y_catalogo(sesion: Session) -> None:
    corte = Corte(
        articulo_id=1,
        titulo="t",
        enlace="https://x/1",
        publicado_en=ANOCHECER,
        zona_texto="GOYA",
        franjas=[{"desde": "08:00", "hasta": "10:00"}],
        primera_vez_visto=ANOCHECER,
        ultima_vez_visto=ANOCHECER,
    )
    sesion.add(corte)
    sesion.flush()
    sesion.add_all(
        [
            CorteDia(articulo_id=1, fecha=date(2026, 11, 5)),
            CorteDia(articulo_id=1, fecha=date(2027, 1, 1)),
            Zona(
                nombre="Goya",
                nombre_norm="goya",
                tipo="localidad",
                veces_vista=3,
                primera_vez=ANOCHECER,
                ultima_vez=ANOCHECER,
            ),
            Zona(
                nombre="Centro",
                nombre_norm="centro",
                tipo="barrio",
                primera_vez=ANOCHECER,
                ultima_vez=ANOCHECER,
            ),
            Suscripcion(nombre="A", canal="email", destino="privado@x.test", creada_en=ANOCHECER),
        ]
    )
    sesion.commit()

    app.dependency_overrides[get_session] = lambda: sesion
    try:
        api = TestClient(app)
        assert api.get("/health").json() == {"status": "ok"}
        cortes = api.get("/cortes", params={"desde": "2026-11-01", "hasta": "2026-11-30"}).json()
        assert [c["fecha"] for c in cortes] == ["2026-11-05"]
        assert cortes[0]["franjas"] == [{"desde": "08:00", "hasta": "10:00"}]
        assert [z["nombre"] for z in api.get("/zonas").json()] == ["Goya"]
        assert api.get("/suscripciones").status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_migraciones_coinciden_con_los_modelos(motor, url_test: str) -> None:
    command.check(config_alembic(url_test))  # Falla si un modelo cambió sin su migración.


def test_tablas_protegidas_de_la_api_publica_de_supabase(motor) -> None:
    with motor.connect() as conexion:
        sin_rls = conexion.execute(
            text(
                "SELECT relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'public' AND c.relkind = 'r' AND NOT c.relrowsecurity"
            )
        ).all()
    assert sin_rls == []
