"""Interpreta los avisos de la DPEC, que son texto escrito a mano.

Formato habitual del título: ``JUEVES 05/11/26 | 07:00 a 08:30 h | SAN ROQUE y zonas de influencia``
pero el histórico muestra muchas variantes (varios días, rangos, campos en otro orden, horarios
erróneos). Por eso cada segmento se clasifica por su contenido y no por su posición, y un dato que
no se entiende se deja vacío con una advertencia: el aviso nunca se descarta por eso.
"""

import calendar
import re
from dataclasses import dataclass, field
from datetime import date, time, timedelta

from bs4 import BeautifulSoup

from scrapper_dpec.texto import normalizar, sin_tildes

_DIAS = ("lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo")
_MAX_DIAS_RANGO = 31

# Tolera errores de tipeo reales: "08/092026" y "03/012/18". "33/13.2 kV" no coincide.
_FECHA = re.compile(r"(?<![\d/])(\d{1,2})/0?(\d{1,2})/?(\d{4}|\d{2})(?![\d/])")
_NUMERO_SUELTO = re.compile(r"(?<![\d/])\d{1,2}(?![\d/])")
_DIA_Y_NUMERO = re.compile(rf"\b({'|'.join(_DIAS)})\s+(\d{{1,2}})(?!\d)")
_FRANJA = re.compile(
    r"(?<![\d.:/])(\d{1,2})(?:[:.](\d{1,2}))?\s*(?:hs?\.?\s*)?a\s+(\d{1,2})(?:[:.](\d{1,2}))?(?![\d/])"
)
_INICIO_HORARIO = re.compile(r"^(?:de\s+|desde\s+|horario:?\s*)*\d{1,2}(?:[:.]\d{1,2}|\s+a\s)")
_INFLUENCIA = re.compile(
    r",?\s*\by?\s*(?:sus\s+)?zonas?\s+(?:de\s+influencias?|aleda[nñ]as?)\b\.*", re.I
)
_RUIDO = re.compile(r"\(?\s*ver\s+zonas\s*\)?|\(?\s*sigue\s*\.*\s*\)?\.*", re.I)
_SEPARADOR_ZONAS = re.compile(r",|;|\s+[yY]\s+")
_TIPOS = (
    ("barrio", re.compile(r"^(?:b\s*[°º]\.?\s*|barrios?\s+)", re.I)),
    ("paraje", re.compile(r"^(?:pjes?\.?\s+|parajes?\s+)", re.I)),
    ("ruta", re.compile(r"^(?:rutas?\b|r\.?[np]\.?\s*n?\s*[°º])", re.I)),
)


@dataclass(frozen=True)
class Franja:
    desde: time
    hasta: time

    def como_dict(self) -> dict[str, str]:
        return {"desde": self.desde.strftime("%H:%M"), "hasta": self.hasta.strftime("%H:%M")}


@dataclass(frozen=True)
class ZonaDetectada:
    nombre: str
    tipo: str  # localidad | barrio | paraje | ruta | otro
    localidad: str = ""  # Localidad a la que pertenece, normalizada, si el título la indica.


@dataclass
class TituloParseado:
    fechas: list[date] = field(default_factory=list)
    franjas: list[Franja] = field(default_factory=list)
    zona_texto: str = ""
    localidades: list[str] = field(default_factory=list)
    zonas: list[ZonaDetectada] = field(default_factory=list)
    advertencias: list[str] = field(default_factory=list)


@dataclass
class CuerpoParseado:
    texto: str
    cronograma: str
    fechas: list[date]
    franjas: list[Franja]


def _a_fecha(dia: int, mes: int, anio: int) -> date | None:
    try:
        return date(anio if anio >= 100 else 2000 + anio, mes, dia)
    except ValueError:
        return None


def _fecha_anterior_con_dia(fin: date, dia: int) -> date | None:
    """Fecha más cercana a ``fin`` hacia atrás con ese día: '30, 01/12/26' cruza de mes."""
    if dia <= fin.day:
        return _a_fecha(dia, fin.month, fin.year)
    mes, anio = (fin.month - 1, fin.year) if fin.month > 1 else (12, fin.year - 1)
    if dia > calendar.monthrange(anio, mes)[1]:
        return None
    return date(anio, mes, dia)


def _fechas_de_segmento(segmento: str, advertencias: list[str]) -> list[date]:
    """Soporta 'JUEVES 05/11/26', 'LUNES 04, MARTES 05/11/26' y 'DEL LUNES 3 AL JUEVES 6/11/26'."""
    texto = sin_tildes(segmento).casefold()
    fechas: list[date] = []
    posicion = 0
    for encontrada in _FECHA.finditer(texto):
        dia, mes, anio = (int(g) for g in encontrada.groups())
        fin = _a_fecha(dia, mes, anio)
        prefijo = texto[posicion : encontrada.start()]
        posicion = encontrada.end()
        if fin is None:
            advertencias.append(f"fecha inválida: {encontrada.group(0)}")
            continue
        sueltos = [int(n) for n in _NUMERO_SUELTO.findall(prefijo)]
        anteriores = [f for n in sueltos if (f := _fecha_anterior_con_dia(fin, n))]
        if anteriores and re.search(r"\bal\b", prefijo):
            inicio = anteriores[0]
            if timedelta(0) <= fin - inicio <= timedelta(days=_MAX_DIAS_RANGO):
                fechas.extend(inicio + timedelta(days=i) for i in range((fin - inicio).days))
            else:
                advertencias.append(f"rango de fechas inválido: {segmento.strip()}")
        else:
            fechas.extend(anteriores)
        fechas.append(fin)

    for nombre, numero in _DIA_Y_NUMERO.findall(texto):
        coincidente = next((f for f in fechas if f.day == int(numero)), None)
        if coincidente and _DIAS[coincidente.weekday()] != nombre:
            advertencias.append(f"el día no coincide con la fecha: {nombre} {coincidente:%d/%m/%Y}")
    return sorted(set(fechas))


def _a_hora(hora: str, minutos: str | None) -> time | None:
    h = int(hora)
    m = int(minutos.ljust(2, "0")) if minutos else 0
    if h == 24 and m == 0:
        return time(23, 59)
    return time(h, m) if h < 24 and m < 60 else None


def parsear_franjas(texto: str) -> list[Franja]:
    franjas: list[Franja] = []
    for h1, m1, h2, m2 in _FRANJA.findall(sin_tildes(texto).casefold()):
        desde, hasta = _a_hora(h1, m1), _a_hora(h2, m2)
        if desde and hasta and desde < hasta:
            franja = Franja(desde, hasta)
            if franja not in franjas:
                franjas.append(franja)
    return franjas


def _limpiar_zona(texto: str) -> str:
    return re.sub(r"\s+", " ", texto).strip(" .,;:-()")


def _partir_localidad(zona_texto: str) -> tuple[str | None, str]:
    """Separa 'SAUCE: B° X' y 'CAPITAL (B° X, B° Y)' en la parte de localidad y el detalle."""
    if ":" in zona_texto:
        izquierda, derecha = zona_texto.split(":", 1)
        return izquierda, derecha
    parentesis = re.match(r"^([^()]+)\((.+)\)\.?$", zona_texto.strip())
    if parentesis:
        return parentesis.group(1), parentesis.group(2)
    return None, zona_texto


def _clasificar(item: str) -> tuple[str | None, str]:
    for tipo, patron in _TIPOS:
        if patron.match(item):
            # El número de ruta es parte del nombre; "B°" y "Paraje" no.
            return tipo, item if tipo == "ruta" else patron.sub("", item, count=1)
    return None, item


def _presentable(nombre: str) -> str:
    return nombre.title() if nombre.isupper() else nombre


def extraer_zonas(zona_texto: str) -> tuple[list[str], list[ZonaDetectada]]:
    """Heurística para el catálogo y las exclusiones: la coincidencia usa el texto completo."""
    limpio = _INFLUENCIA.sub("", _RUIDO.sub("", zona_texto))
    izquierda, detalle = _partir_localidad(limpio)

    localidades: list[str] = []
    zonas: list[ZonaDetectada] = []

    def agregar(nombre: str, tipo: str, localidad: str = "") -> None:
        nombre = _presentable(_limpiar_zona(nombre))
        if not nombre or nombre.isdigit() or len(nombre) > 60:
            return
        zona = ZonaDetectada(nombre, tipo, localidad)
        if zona not in zonas:
            zonas.append(zona)

    if izquierda is not None:
        for item in _SEPARADOR_ZONAS.split(izquierda):
            normalizada = normalizar(item)
            if normalizada and normalizada not in localidades:
                localidades.append(normalizada)
                agregar(item, "localidad")

    items = [_limpiar_zona(i) for i in _SEPARADOR_ZONAS.split(detalle) if _limpiar_zona(i)]
    # Sin "LOCALIDAD:" y con barrios, es una zona de Capital que no la nombra: lo que no tiene
    # prefijo no es una localidad. Sin barrios, es una lista de localidades ("SAN ROQUE, GOYA").
    hay_tipados = any(_clasificar(i)[0] for i in items)
    duena = localidades[0] if len(localidades) == 1 else ""
    for item in items:
        tipo, nombre = _clasificar(item)
        if tipo:
            agregar(nombre, tipo, duena)
        elif izquierda is None and not hay_tipados:
            normalizada = normalizar(nombre)
            if normalizada and not normalizada.isdigit() and normalizada not in localidades:
                localidades.append(normalizada)
            agregar(nombre, "localidad")
        else:
            agregar(nombre, "otro", duena)
    return localidades, zonas


def parsear_titulo(titulo: str) -> TituloParseado:
    resultado = TituloParseado()
    if "|" not in titulo:
        resultado.zona_texto = _limpiar_zona(titulo)
        resultado.advertencias.append("título sin el formato esperado")
        return resultado

    resto: list[str] = []
    hubo_horario = False
    for segmento in titulo.split("|"):
        segmento = segmento.strip()
        comparable = sin_tildes(segmento).casefold()
        if _FECHA.search(comparable):
            resultado.fechas.extend(_fechas_de_segmento(segmento, resultado.advertencias))
            # Hay títulos con el horario junto a la fecha: "SÁBADO 18/03/17 de 14 a 19 Hs."
            for franja in parsear_franjas(segmento):
                if franja not in resultado.franjas:
                    resultado.franjas.append(franja)
        elif _INICIO_HORARIO.match(comparable):
            hubo_horario = True
            for franja in parsear_franjas(segmento):
                if franja not in resultado.franjas:
                    resultado.franjas.append(franja)
        elif segmento:
            resto.append(segmento)

    resultado.fechas = sorted(set(resultado.fechas))
    resultado.zona_texto = _limpiar_zona(" ".join(resto))
    resultado.localidades, resultado.zonas = extraer_zonas(" ".join(resto))
    if not resultado.fechas:
        resultado.advertencias.append("no se pudo interpretar la fecha")
    if hubo_horario and not resultado.franjas:
        resultado.advertencias.append("no se pudo interpretar el horario")
    return resultado


def parsear_cuerpo(html: str) -> CuerpoParseado | None:
    """Extrae el texto del aviso. El cuerpo manda sobre el título en horarios y zonas.

    Devuelve ``None`` si la página no tiene el contenedor esperado: buscar en la página entera
    daría coincidencias falsas con el menú y los banners.
    """
    contenedor = BeautifulSoup(html, "html.parser").select_one("section.articulo-contenido")
    if contenedor is None:
        return None
    lineas = [
        limpia
        for linea in contenedor.get_text("\n").splitlines()
        if (limpia := re.sub(r"\s+", " ", linea).strip())
    ]
    texto = "\n".join(lineas)

    desde = next((i for i, linea in enumerate(lineas) if linea.upper().startswith("FECHA")), None)
    cronograma = "\n".join(lineas[desde:]) if desde is not None else ""

    franjas: list[Franja] = []
    fechas: list[date] = []
    descartadas: list[str] = []
    for linea in lineas:
        mayusculas = linea.upper()
        if mayusculas.startswith("HORARIO"):
            franjas.extend(f for f in parsear_franjas(linea) if f not in franjas)
        elif mayusculas.startswith("FECHA"):
            fechas.extend(_fechas_de_segmento(linea, descartadas))
    return CuerpoParseado(texto, cronograma, sorted(set(fechas)), franjas)
