"""Patrón Strategy: el resto del sistema solo conoce ``Notifier``, no cómo se envía cada mensaje.

Agregar un canal (WhatsApp, Telegram) es crear una subclase y registrarla en ``crear_notifier``.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class Mensaje:
    asunto: str
    cuerpo: str


class ErrorNotificacion(Exception):
    """El mensaje no se pudo enviar; se reintenta en la próxima ejecución."""


class Notifier(ABC):
    @abstractmethod
    def enviar(self, destino: str, mensaje: Mensaje) -> None:
        """Envía el mensaje o lanza ``ErrorNotificacion``."""
