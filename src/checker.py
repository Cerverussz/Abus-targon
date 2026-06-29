"""Orquestador: recorre tiendas, evalúa estado, notifica cambios y guarda estado.

Uso:
    python -m src.checker
"""
from __future__ import annotations

import logging
import os
import sys
import traceback
from pathlib import Path

import yaml
from dotenv import load_dotenv

from .models import CheckResult, Status
from .notifier import notify
from .state import (
    DEFAULT_STATE_FILE,
    Notification,
    diff,
    load_state,
    save_state,
    update_store,
)
from .stores import get_detector

logger = logging.getLogger("targon")

DEFAULT_CONFIG = os.getenv("STORES_CONFIG", "config/stores.yaml")


def load_config(path: str = DEFAULT_CONFIG) -> dict:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    stores = data.get("stores", {})
    if not stores:
        raise RuntimeError(f"No hay tiendas configuradas en {path}.")
    return stores


def check_store(store_key: str, cfg: dict) -> CheckResult:
    """Verifica una tienda; cualquier fallo se captura como ERROR."""
    method = cfg.get("method")
    try:
        detector = get_detector(method)
        result = detector.check(store_key, cfg)
        logger.info(
            "[%s] %s | precio=%s %s | color=%s",
            store_key,
            result.status.value,
            result.price if result.price is not None else "—",
            result.currency or "",
            result.color or "—",
        )
        return result
    except Exception as exc:  # noqa: BLE001 - un fallo no rompe la corrida
        logger.error("[%s] ERROR: %s", store_key, exc)
        logger.debug("%s", traceback.format_exc())
        return CheckResult(
            store_key=store_key,
            store_name=cfg.get("name", store_key),
            country=cfg.get("country", "—"),
            url=cfg.get("url", ""),
            currency=cfg.get("currency"),
            status=Status.ERROR,
            error=str(exc),
        )


def run() -> int:
    load_dotenv()
    logging.basicConfig(
        level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(message)s",
    )

    stores = load_config()
    state = load_state()

    results: list[CheckResult] = []
    notifications: list[Notification] = []

    logger.info("=== Corrida Targon Watch: %d tiendas ===", len(stores))
    for store_key, cfg in stores.items():
        if not cfg.get("enabled", True):
            logger.info("[%s] deshabilitada (skip).", store_key)
            continue
        result = check_store(store_key, cfg)
        results.append(result)

        notif = diff(state, result)
        if notif:
            notifications.append(notif)
        update_store(state, result)

    # Notificar: primero las transiciones a DISPONIBLE.
    notifications.sort(key=lambda n: 0 if n.is_available_transition else 1)
    sent = 0
    for notif in notifications:
        try:
            notify(notif)
            sent += 1
        except Exception as exc:  # noqa: BLE001 - no perder el estado por Telegram
            logger.error(
                "[%s] no se pudo enviar la notificación: %s",
                notif.result.store_key, exc,
            )

    save_state(state)

    # Resumen de la corrida.
    summary = ", ".join(f"{r.store_key}={r.status.value}" for r in results)
    logger.info("=== Resumen: %s ===", summary)
    logger.info(
        "Notificaciones enviadas: %d/%d | estado guardado en %s",
        sent, len(notifications), DEFAULT_STATE_FILE,
    )
    return 0


if __name__ == "__main__":
    sys.exit(run())
