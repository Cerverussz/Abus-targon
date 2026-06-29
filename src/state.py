"""Lectura/escritura de state.json y diff para notificaciones idempotentes."""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .models import CheckResult, Status

logger = logging.getLogger(__name__)

DEFAULT_STATE_FILE = os.getenv("STATE_FILE", "state.json")


@dataclass
class Notification:
    """Aviso a enviar por un cambio relevante."""

    result: CheckResult
    reason: str          # "available" | "price_change"
    previous_price: Optional[float] = None

    @property
    def is_available_transition(self) -> bool:
        return self.reason == "available"


def load_state(path: str = DEFAULT_STATE_FILE) -> dict:
    """Carga state.json. Devuelve estructura vacía si no existe o está corrupto."""
    p = Path(path)
    if not p.exists():
        return {"stores": {}}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or "stores" not in data:
            logger.warning("state.json con formato inesperado; se reinicia.")
            return {"stores": {}}
        return data
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("No se pudo leer state.json (%s); se reinicia.", exc)
        return {"stores": {}}


def save_state(state: dict, path: str = DEFAULT_STATE_FILE) -> None:
    """Guarda state.json de forma legible y estable (claves ordenadas)."""
    p = Path(path)
    p.write_text(
        json.dumps(state, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def diff(previous: dict, result: CheckResult) -> Optional[Notification]:
    """Decide si un resultado merece notificación frente al estado previo.

    Reglas (anti-spam, idempotentes):
      a) Transición a AVAILABLE desde cualquier otro estado -> notificar (prioridad).
      b) Sigue AVAILABLE pero el precio cambió -> notificar.
    Cualquier otro caso (incluido ERROR o estado sin cambio) -> None.
    """
    if result.status == Status.ERROR:
        return None

    prev = previous.get("stores", {}).get(result.store_key)
    prev_status = prev.get("status") if prev else None
    prev_price = prev.get("price") if prev else None

    if result.status == Status.AVAILABLE:
        if prev_status != Status.AVAILABLE.value:
            return Notification(result=result, reason="available")
        if result.price is not None and result.price != prev_price:
            return Notification(
                result=result, reason="price_change", previous_price=prev_price
            )
    return None


def update_store(state: dict, result: CheckResult) -> None:
    """Actualiza el estado para una tienda.

    En ERROR se conserva el último estado bueno para no perder el baseline
    (evita falsas "transiciones" en la siguiente corrida exitosa).
    """
    state.setdefault("stores", {})
    if result.status == Status.ERROR:
        existing = state["stores"].get(result.store_key)
        if existing is not None:
            existing["last_error"] = result.error
            existing["last_checked"] = result.checked_at
        else:
            # Nunca tuvimos un estado bueno: registramos el error como baseline.
            entry = result.to_state()
            entry["last_error"] = result.error
            state["stores"][result.store_key] = entry
        return
    state["stores"][result.store_key] = result.to_state()
