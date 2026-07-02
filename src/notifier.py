"""Notificaciones por Telegram Bot API."""
from __future__ import annotations

import html
import logging
import os
import sys

import httpx

from .models import Status
from .state import Notification

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"

_STATUS_LABEL = {
    Status.AVAILABLE: "✅ DISPONIBLE",
    Status.OUT_OF_STOCK: "❌ Agotado",
    Status.PREORDER: "🕒 Preventa / backorder",
    Status.NOT_LISTED: "🔍 No listado",
    Status.ERROR: "⚠️ Error",
}


def _credentials() -> tuple[str, str]:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        raise RuntimeError(
            "Faltan TELEGRAM_BOT_TOKEN y/o TELEGRAM_CHAT_ID en el entorno (.env)."
        )
    return token, chat_id


def send(text: str) -> None:
    """Envía un mensaje HTML a Telegram. Lanza excepción si la API falla."""
    token, chat_id = _credentials()
    resp = httpx.post(
        TELEGRAM_API.format(token=token),
        json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
        },
        timeout=20,
    )
    if resp.status_code != 200:
        # Telegram devuelve el motivo exacto en el cuerpo JSON ("description");
        # lo exponemos para diagnosticar (chat sin iniciar, chat_id erróneo...).
        description = ""
        try:
            description = resp.json().get("description", "")
        except Exception:  # noqa: BLE001
            description = (resp.text or "")[:200]
        raise RuntimeError(
            f"Telegram respondió {resp.status_code}: {description} "
            f"(chat_id={chat_id!r})"
        )
    logger.info("Telegram: mensaje enviado.")


def _fmt_price(notif: Notification) -> str:
    r = notif.result
    if r.price is None:
        return "—"
    cur = r.currency or ""
    return f"{r.price:g} {cur}".strip()


def format_notification(notif: Notification) -> str:
    """Construye el mensaje HTML para un cambio relevante."""
    r = notif.result
    header = (
        "🚨 <b>¡Abus Targon MIPS DISPONIBLE!</b>"
        if notif.is_available_transition
        else "💸 <b>Cambio de precio — Abus Targon MIPS</b>"
    )
    lines = [
        header,
        "",
        f"🏬 <b>Tienda:</b> {html.escape(r.store_name)} ({html.escape(r.country)})",
        f"📦 <b>Talla:</b> {html.escape(r.size)} (55–58 cm)",
        f"📊 <b>Estado:</b> {_STATUS_LABEL.get(r.status, r.status.value)}",
    ]
    if notif.reason == "price_change" and notif.previous_price is not None:
        prev_cur = r.currency or ""
        lines.append(
            f"💰 <b>Precio:</b> {notif.previous_price:g} {prev_cur} → "
            f"{_fmt_price(notif)}".strip()
        )
    else:
        lines.append(f"💰 <b>Precio:</b> {_fmt_price(notif)}")
    if r.color:
        lines.append(f"🎨 <b>Color:</b> {html.escape(r.color)}")
    lines.append(f'🔗 <a href="{html.escape(r.url, quote=True)}">Ver producto</a>')
    return "\n".join(lines)


def notify(notif: Notification) -> None:
    """Formatea y envía una notificación de cambio."""
    send(format_notification(notif))


def format_manual_reminder(results) -> str:
    """Mensaje-recordatorio para tiendas que no se pudieron verificar solas."""
    lines = [
        "🔎 <b>Revisión manual — Abus Targon MIPS (talla M)</b>",
        "",
        "El monitor <b>no pudo verificar</b> estas tiendas automáticamente "
        "(anti-bot). Revisa a mano si hay disponibilidad de la M (55–58 cm):",
        "",
    ]
    for r in results:
        lines.append(
            f'• <a href="{html.escape(r.url, quote=True)}">'
            f"{html.escape(r.store_name)}</a> ({html.escape(r.country)})"
        )
    return "\n".join(lines)


def notify_manual(results) -> None:
    """Envía un único recordatorio consolidado de revisión manual."""
    if results:
        send(format_manual_reminder(results))


def _test() -> int:
    """Modo prueba: valida credenciales enviando un mensaje de comprobación."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        send(
            "🤖 <b>Targon Watch</b>\n"
            "Mensaje de prueba: tus credenciales de Telegram funcionan. ✅"
        )
    except Exception as exc:  # noqa: BLE001 - feedback directo al usuario
        logger.error("Falló el envío de prueba: %s", exc)
        return 1
    print("OK: mensaje de prueba enviado a Telegram.")
    return 0


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()
    if "--test" in sys.argv:
        sys.exit(_test())
    print("Uso: python -m src.notifier --test")
    sys.exit(2)
