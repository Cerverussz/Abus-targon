"""Modelo de datos compartido por detectores, estado y notificador."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class Status(str, Enum):
    """Estado real de la talla M en una tienda.

    Hereda de ``str`` para serializar/deserializar a JSON sin conversiones.
    """

    AVAILABLE = "AVAILABLE"          # La M es realmente comprable.
    OUT_OF_STOCK = "OUT_OF_STOCK"    # Listado pero agotado.
    PREORDER = "PREORDER"            # Preventa / backorder.
    NOT_LISTED = "NOT_LISTED"        # El modelo no aparece en la tienda.
    ERROR = "ERROR"                  # Falló la verificación (no rompe la corrida).

    def __str__(self) -> str:  # pragma: no cover - cosmético
        return self.value


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class CheckResult:
    """Resultado de verificar una tienda en una corrida."""

    store_key: str
    store_name: str
    country: str
    status: Status
    url: str
    price: Optional[float] = None
    currency: Optional[str] = None
    color: Optional[str] = None
    size: str = "M"
    error: Optional[str] = None
    checked_at: str = field(default_factory=_now_iso)

    def to_state(self) -> dict:
        """Representación persistible en state.json (lo mínimo para el diff)."""
        return {
            "status": self.status.value,
            "price": self.price,
            "currency": self.currency,
            "color": self.color,
            "size": self.size,
            "url": self.url,
            "checked_at": self.checked_at,
        }
