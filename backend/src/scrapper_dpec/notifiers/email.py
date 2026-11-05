"""Envío por SMTP (Gmail con contraseña de aplicación)."""

import re
import smtplib
from email.message import EmailMessage

from scrapper_dpec.notifiers.base import ErrorNotificacion, Mensaje, Notifier


class EmailNotifier(Notifier):
    def __init__(self, host: str, puerto: int, usuario: str, contrasena: str) -> None:
        self._host = host
        self._puerto = puerto
        self._usuario = usuario
        self._contrasena = contrasena

    def enviar(self, destino: str, mensaje: Mensaje) -> None:
        if not self._usuario or not self._contrasena:
            raise ErrorNotificacion("Faltan SMTP_USER o SMTP_PASSWORD.")

        correo = EmailMessage()
        correo["From"] = f"Avisos de cortes <{self._usuario}>"
        correo["To"] = destino
        # El asunto incluye texto de la DPEC: un salto de línea no debe poder agregar encabezados.
        correo["Subject"] = re.sub(r"\s+", " ", mensaje.asunto).strip()
        correo.set_content(mensaje.cuerpo)

        try:
            with smtplib.SMTP(self._host, self._puerto, timeout=30) as smtp:
                smtp.starttls()
                smtp.login(self._usuario, self._contrasena)
                smtp.send_message(correo)
        except (smtplib.SMTPException, OSError) as error:
            # Solo el tipo: el detalle puede incluir direcciones y los logs de Actions son públicos.
            raise ErrorNotificacion(f"Falló el envío SMTP: {type(error).__name__}") from error
