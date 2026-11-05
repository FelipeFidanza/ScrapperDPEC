"""Canales de notificación."""

from scrapper_dpec.config import Settings
from scrapper_dpec.notifiers.base import ErrorNotificacion, Mensaje, Notifier
from scrapper_dpec.notifiers.email import EmailNotifier

__all__ = [
    "CANAL_EMAIL",
    "EmailNotifier",
    "ErrorNotificacion",
    "Mensaje",
    "Notifier",
    "crear_notifier",
]

CANAL_EMAIL = "email"


def crear_notifier(canal: str, settings: Settings) -> Notifier:
    """Elige la implementación según el canal de la suscripción."""
    if canal == CANAL_EMAIL:
        return EmailNotifier(
            settings.smtp_host,
            settings.smtp_port,
            settings.smtp_user,
            settings.smtp_password.get_secret_value(),
        )
    raise ErrorNotificacion(f"Canal desconocido: {canal}")
