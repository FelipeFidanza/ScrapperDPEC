"""Hora local. Los runners de GitHub Actions están en UTC, pero "mañana" es en Corrientes."""

from datetime import datetime
from zoneinfo import ZoneInfo

ZONA_HORARIA = ZoneInfo("America/Argentina/Cordoba")  # La zona IANA que incluye a Corrientes.


def ahora() -> datetime:
    return datetime.now(ZONA_HORARIA)
