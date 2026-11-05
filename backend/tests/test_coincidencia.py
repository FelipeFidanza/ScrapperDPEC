"""Decide si un aviso le corresponde a un suscriptor: es la regla más importante del sistema."""

import json

import pytest

from conftest import leer_fixture
from scrapper_dpec.modelos import Corte, Suscripcion
from scrapper_dpec.notificador import palabra_que_coincide
from scrapper_dpec.parser import parsear_titulo


def _suscripcion(claves: list[str], excluidas: list[str] | None = None) -> Suscripcion:
    return Suscripcion(
        nombre="Ana",
        canal="email",
        destino="a@x.test",
        palabras_clave=claves,
        localidades_excluidas=excluidas or [],
    )


def _corte(titulo: str, cuerpo: str | None = None) -> Corte:
    return Corte(
        titulo=titulo,
        cuerpo=cuerpo,
        localidades=parsear_titulo(titulo).localidades,
    )


def test_ignora_tildes_y_mayusculas() -> None:
    corte = _corte("LUNES 02/11/26 | 8 a 12 Hs | CAPITAL: B° SANTA TERESITA.")
    assert palabra_que_coincide(_suscripcion(["Santa Teresita"]), corte) == "Santa Teresita"
    corte = _corte("LUNES 02/11/26 | 8 a 12 Hs | CAPITAL: Perichón.")
    assert palabra_que_coincide(_suscripcion(["perichon"]), corte) == "perichon"


def test_encuentra_la_zona_solo_en_el_cuerpo() -> None:
    corte = _corte(
        "MARTES 08/09/2026 | De 08:13 y de 08:12 | CAPITAL  (Ver zonas)",
        "ZONAS: Barrios Perichón, Comisaría nueva",
    )
    assert palabra_que_coincide(_suscripcion(["Perichón"]), corte) == "Perichón"


def test_no_coincide_con_otra_zona() -> None:
    corte = _corte("LUNES 02/11/26 | 8 a 12 Hs | CAPITAL: B° Santa Rosa.")
    assert palabra_que_coincide(_suscripcion(["Santa Teresita"]), corte) is None


def test_excluye_el_homonimo_de_otra_ciudad() -> None:
    corte = _corte("MIÉRCOLES 18/09/19 | 07:00 a 08:00 | CURUZÚ CUATIÁ: barrios Santa Teresita.")
    assert palabra_que_coincide(_suscripcion(["Santa Teresita"]), corte)
    sub = _suscripcion(["Santa Teresita"], ["Curuzú Cuatiá"])
    assert palabra_que_coincide(sub, corte) is None


def test_un_barrio_con_nombre_de_localidad_excluida_no_descarta_el_aviso() -> None:
    corte = _corte("LUNES 02/11/26 | 8 a 12 Hs | CAPITAL: B° Bella Vista, B° Santa Teresita.")
    assert palabra_que_coincide(_suscripcion(["Santa Teresita"], ["Bella Vista"]), corte)


def test_solo_excluye_si_todas_las_localidades_estan_excluidas() -> None:
    corte = _corte("LUNES 02/11/26 | 8 a 12 Hs | BELLA VISTA y CAPITAL: Santa Teresita.")
    assert palabra_que_coincide(_suscripcion(["Santa Teresita"], ["Bella Vista"]), corte)


def test_aviso_sin_localidad_nunca_se_excluye() -> None:
    corte = _corte("LUNES 02/11/26 | 8 a 12 Hs | COMPLEJO DE GOLF, ZONA DE PLAYA SANTA TERESITA.")
    assert corte.localidades  # Sin barrios, los toma como localidades...
    assert palabra_que_coincide(_suscripcion(["Santa Teresita"], ["Bella Vista"]), corte)


@pytest.mark.parametrize(
    ("excluidas", "avisos_esperados"),
    [([], 51), (["Curuzú Cuatiá"], 34), (["Curuzú Cuatiá", "Bella Vista"], 30)],
)
def test_santa_teresita_contra_el_historico(excluidas: list[str], avisos_esperados: int) -> None:
    """Los 51 avisos históricos que la mencionan: excluir ciudades deja solo los de Capital."""
    historico = json.loads(leer_fixture("titulos_historicos.json"))
    sub = _suscripcion(["Santa Teresita"], excluidas)
    conteo = sum(1 for t in historico if palabra_que_coincide(sub, _corte(t["titulo"])))
    assert conteo == avisos_esperados
