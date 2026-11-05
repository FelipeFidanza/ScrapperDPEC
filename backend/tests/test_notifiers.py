import smtplib
from unittest.mock import patch

import pytest

from scrapper_dpec.config import Settings, normalizar_url_db
from scrapper_dpec.notifiers import (
    CANAL_EMAIL,
    EmailNotifier,
    ErrorNotificacion,
    Mensaje,
    crear_notifier,
)

MENSAJE = Mensaje(asunto="Corte\nBcc: intruso@x.test", cuerpo="Mañana se corta la luz.")


def _notifier() -> EmailNotifier:
    return EmailNotifier("smtp.test", 587, "yo@x.test", "clave")


def test_envia_por_smtp_con_tls() -> None:
    with patch("scrapper_dpec.notifiers.email.smtplib.SMTP") as smtp:
        _notifier().enviar("destino@x.test", MENSAJE)
    conexion = smtp.return_value.__enter__.return_value
    conexion.starttls.assert_called_once()
    conexion.login.assert_called_once_with("yo@x.test", "clave")
    correo = conexion.send_message.call_args.args[0]
    assert correo["To"] == "destino@x.test"
    assert "Mañana se corta la luz." in correo.get_content()


def test_asunto_no_permite_inyectar_encabezados() -> None:
    with patch("scrapper_dpec.notifiers.email.smtplib.SMTP") as smtp:
        _notifier().enviar("destino@x.test", MENSAJE)
    correo = smtp.return_value.__enter__.return_value.send_message.call_args.args[0]
    assert correo["Bcc"] is None
    assert "\n" not in correo["Subject"]


def test_error_smtp_no_expone_direcciones() -> None:
    error = smtplib.SMTPRecipientsRefused({"destino@x.test": (550, b"no")})
    with patch("scrapper_dpec.notifiers.email.smtplib.SMTP") as smtp:
        smtp.return_value.__enter__.return_value.send_message.side_effect = error
        with pytest.raises(ErrorNotificacion) as capturado:
            _notifier().enviar("destino@x.test", MENSAJE)
    assert "destino@x.test" not in str(capturado.value)


def test_sin_credenciales_falla_sin_conectar() -> None:
    with (
        patch("scrapper_dpec.notifiers.email.smtplib.SMTP") as smtp,
        pytest.raises(ErrorNotificacion),
    ):
        EmailNotifier("smtp.test", 587, "", "").enviar("d@x.test", MENSAJE)
    smtp.assert_not_called()


def test_factory_por_canal() -> None:
    settings = Settings(_env_file=None, smtp_user="yo@x.test", smtp_password="c")
    assert isinstance(crear_notifier(CANAL_EMAIL, settings), EmailNotifier)
    with pytest.raises(ErrorNotificacion):
        crear_notifier("palomas", settings)


def test_url_de_supabase_obtiene_driver() -> None:
    assert normalizar_url_db("postgresql://u:p@h/db") == "postgresql+psycopg://u:p@h/db"
    assert normalizar_url_db("postgres://u:p@h/db") == "postgresql+psycopg://u:p@h/db"
    assert normalizar_url_db("postgresql+psycopg://u:p@h/db") == "postgresql+psycopg://u:p@h/db"
