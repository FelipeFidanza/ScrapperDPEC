import json
from datetime import date, time

import pytest

from conftest import leer_fixture
from scrapper_dpec.parser import Franja, parsear_cuerpo, parsear_franjas, parsear_titulo
from scrapper_dpec.texto import contiene_frase, normalizar


def _f(texto: str) -> list[date]:
    return [date.fromisoformat(x) for x in texto.split()]


@pytest.mark.parametrize(
    ("titulo", "fechas"),
    [
        ("JUEVES 05/11/26 |  07:00 a 08:30 h | SAN ROQUE", "2026-11-05"),
        ("MARTES 08/09/2026 | De 07:00 a 08:00 Hs | Derqui", "2026-09-08"),
        ("MARTES 5/12/17 | 7:30 a 13:00 Hs | CAPITAL", "2017-12-05"),
        ("VIERNES 15 y SÁBADO 16/11/19 | 08:00 a 08:30 | GOYA", "2019-11-15 2019-11-16"),
        (
            "MIÉRCOLES 04, JUEVES 05, VIERNES 06, MARTES 10/11/26  | 08:00 a 16:00 h | MERCEDES",
            "2026-11-04 2026-11-05 2026-11-06 2026-11-10",
        ),
        (
            "Del DOMINGO 3 al JUEVES 7/12/17 | 7:00 a 14:00 Hs | LORETO",
            "2017-12-03 2017-12-04 2017-12-05 2017-12-06 2017-12-07",
        ),
        (
            "JUEVES 04/01/18 | VIERNES 05/01/18 y SABADO 06/01/18 |06:00 a 09:00 Hs. | ALVEAR",
            "2018-01-04 2018-01-05 2018-01-06",
        ),
        ("LUNES 30, MARTES 01/12/26 | 8 a 12 Hs | GOYA", "2026-11-30 2026-12-01"),
        ("JUEVES 31/12/26, VIERNES 01/01/27 | 8 a 12 Hs | GOYA", "2026-12-31 2027-01-01"),
        ("MIERCOLES 03/012/18 |  8:00 a 13:00 Hs. | B° SAN ROQUE ESTE", "2018-12-03"),
        ("CAPITAL (B° La Rozada) | 10/03/17 | 7 A 11 hS.", "2017-03-10"),
    ],
)
def test_fechas(titulo: str, fechas: str) -> None:
    assert parsear_titulo(titulo).fechas == _f(fechas)


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("07:00 a 08:30 h", [("07:00", "08:30")]),
        ("De 08:00 a 09:00 Hs.", [("08:00", "09:00")]),
        ("14 a 16 Hs.", [("14:00", "16:00")]),
        ("De 14 a 17:30 Hs", [("14:00", "17:30")]),
        ("08:00 A 10:00 Hs.", [("08:00", "10:00")]),
        ("De 07:00 a 09:30 Hs. y de 14:00 a 17:00 Hs.", [("07:00", "09:30"), ("14:00", "17:00")]),
        ("De 08:13 y de 08:12", []),  # Error real de la DPEC: no hay ningún rango.
        ("25:00 a 26:00", []),
        ("18:00 a 08:00", []),
    ],
)
def test_franjas(texto: str, esperado: list[tuple[str, str]]) -> None:
    obtenido = [
        (f.desde.strftime("%H:%M"), f.hasta.strftime("%H:%M")) for f in parsear_franjas(texto)
    ]
    assert obtenido == esperado


def test_campos_en_otro_orden() -> None:
    p = parsear_titulo("VIERNES 23/06/23 | SAN COSME | De 08:00 a 08:15 Hs")
    assert p.fechas == [date(2023, 6, 23)]
    assert p.franjas == [Franja(time(8), time(8, 15))]
    assert p.zona_texto == "SAN COSME"


def test_horario_junto_a_la_fecha() -> None:
    p = parsear_titulo("SÁBADO 18/03/17 de 14 a 19 Hs. | DOMINGO 19/03/17 de 7 a 12 Hs. | SALADAS")
    assert p.fechas == _f("2017-03-18 2017-03-19")
    assert p.franjas == [Franja(time(14), time(19)), Franja(time(7), time(12))]


def test_horario_erroneo_conserva_fecha_y_advierte() -> None:
    p = parsear_titulo("MARTES 08/09/2026 | De 08:13 y de 08:12 | CAPITAL  (Ver zonas)")
    assert p.fechas == [date(2026, 9, 8)]
    assert p.franjas == []
    assert p.localidades == ["capital"]
    assert "no se pudo interpretar el horario" in p.advertencias


def test_titulo_sin_formato_no_rompe() -> None:
    p = parsear_titulo("BELLA VISTA: Cortes Rotativos de 2 horas de duración.")
    assert p.fechas == []
    assert p.advertencias


def test_dia_de_la_semana_incorrecto_advierte() -> None:
    p = parsear_titulo("MARTES 6/05/17 | 14:00 a 17:00 Hs. | MERCEDES")
    assert p.fechas == [date(2017, 5, 6)]
    assert any("no coincide" in a for a in p.advertencias)


@pytest.mark.parametrize(
    ("zona", "localidades"),
    [
        ("SAN ROQUE, BELLA VISTA y zonas de influencia.", ["san roque", "bella vista"]),
        ("SAUCE: B° Cementerio, Segunda Sección y zonas de influencia.", ["sauce"]),
        ("CAPITAL y SAN LUIS DEL PALMAR: Ruta 5 y zonas", ["capital", "san luis del palmar"]),
        ("CAPITAL (B° santa Teresita, B° Chiquita y zonas de influencia).", ["capital"]),
        ("CAPITAL  (Ver zonas)", ["capital"]),
        ("FELIPE YOFRE Y CHAVARRÍA", ["felipe yofre", "chavarria"]),
        ("B° 17 de Agosto, B° San Marcelo, Mercado de Concentración", []),
        ("GARRUCHOS, sus zonas de influencias", ["garruchos"]),
    ],
)
def test_localidades(zona: str, localidades: list[str]) -> None:
    assert parsear_titulo(f"LUNES 02/11/26 | 8 a 12 Hs | {zona}").localidades == localidades


def test_tipos_de_zona() -> None:
    p = parsear_titulo(
        "LUNES 02/11/26 | 8 a 12 Hs | MERCEDES: Ruta N° 40, B° Centro, Pjes. Arroyo Grande."
    )
    assert [(z.nombre, z.tipo, z.localidad) for z in p.zonas] == [
        ("Mercedes", "localidad", ""),
        ("Ruta N° 40", "ruta", "mercedes"),
        ("Centro", "barrio", "mercedes"),
        ("Arroyo Grande", "paraje", "mercedes"),
    ]


def test_cuerpo_con_horarios_por_zona() -> None:
    c = parsear_cuerpo(leer_fixture("articulo_8679_ver_zonas.html"))
    assert c is not None
    assert c.fechas == [date(2026, 9, 8)]  # El cuerpo real dice "08/092026".
    assert c.franjas == [Franja(time(8), time(13)), Franja(time(8), time(12))]
    assert "Perichón" in c.cronograma
    assert c.cronograma.startswith("FECHA:")
    assert "Trabajá con nosotros" not in c.texto  # No se mezcla con el resto de la página.


def test_cuerpo_sin_contenedor_devuelve_none() -> None:
    assert parsear_cuerpo("<html><body><p>rediseño</p></body></html>") is None


def test_normalizar() -> None:
    assert normalizar("B° SANTA  Teresita.") == "b santa teresita"
    assert normalizar("CURUZÚ CUATIÁ") == "curuzu cuatia"
    assert contiene_frase("playa santa teresita sur", "santa teresita")
    assert not contiene_frase("santa teresitas", "santa teresita")
    assert not contiene_frase("algo", "")


def test_cubre_casi_todo_el_historico_real() -> None:
    """Protege contra regresiones: se mide con los 1496 títulos con formato moderno."""
    historico = json.loads(leer_fixture("titulos_historicos.json"))
    modernos = [t for t in historico if t["fechaIso"] >= "2017-03-15"]
    assert len(modernos) > 1400
    sin_fecha = [t for t in modernos if not parsear_titulo(t["titulo"]).fechas]
    sin_horario = [t for t in modernos if not parsear_titulo(t["titulo"]).franjas]
    assert len(sin_fecha) <= 2, sin_fecha
    assert len(sin_horario) / len(modernos) < 0.01


def test_fechas_cercanas_a_la_publicacion() -> None:
    historico = json.loads(leer_fixture("titulos_historicos.json"))
    lejanas = []
    for t in historico:
        publicado = date.fromisoformat(t["fechaIso"][:10])
        for fecha in parsear_titulo(t["titulo"]).fechas:
            if not -7 <= (fecha - publicado).days <= 45:
                lejanas.append((t["articuloId"], t["titulo"][:60]))
                break
    # Único caso conocido: 1195, "MARTES 6/05/17" publicado en junio (error de la DPEC).
    assert len(lejanas) <= 3, lejanas
