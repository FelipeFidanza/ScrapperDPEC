"""Normalización de texto para comparar zonas sin depender de tildes o mayúsculas."""

import re
import unicodedata

_NO_ALFANUMERICO = re.compile(r"[^a-z0-9]+")


def sin_tildes(texto: str) -> str:
    descompuesto = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in descompuesto if not unicodedata.combining(c))


def normalizar(texto: str) -> str:
    """'B° SANTA Teresita.' -> 'b santa teresita'."""
    return _NO_ALFANUMERICO.sub(" ", sin_tildes(texto).casefold()).strip()


def contiene_frase(texto_normalizado: str, frase_normalizada: str) -> bool:
    """Busca palabras completas: 'santa rosa' no coincide dentro de 'santa rosario'."""
    if not frase_normalizada:
        return False
    return f" {frase_normalizada} " in f" {texto_normalizado} "
