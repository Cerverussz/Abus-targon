"""Interfaz base y utilidades compartidas por los detectores."""
from __future__ import annotations

import logging
from typing import Optional

from ..models import CheckResult, Status

logger = logging.getLogger(__name__)

# User-agent realista (Chrome estable en Windows). Tráfico mínimo: 3 corridas/día.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

DEFAULT_TIMEOUT = 30  # segundos

# Señales de pantallas anti-bot / challenge (Cloudflare, Akamai, etc.).
# Si la página es una de éstas, NO pudimos leer el producto: hay que tratarlo
# como ERROR (lectura no fiable), nunca como AGOTADO (evita falsos negativos).
ANTIBOT_KEYWORDS = [
    "un momento…", "un momento...", "just a moment", "checking your browser",
    "verifying you are human", "verify you are human", "attention required",
    "access denied", "acceso denegado", "cloudflare", "ddos protection",
    "enable javascript and cookies", "/cdn-cgi/", "ray id",
]


def is_antibot(*texts: str) -> bool:
    """True si algún texto (título, cuerpo) parece una pantalla anti-bot."""
    blob = " ".join(t for t in texts if t).lower()
    return any(kw in blob for kw in ANTIBOT_KEYWORDS)


class Detector:
    """Contrato común. Cada método de detección implementa ``check``."""

    method: str = "base"

    def check(self, store_key: str, cfg: dict) -> CheckResult:  # pragma: no cover
        raise NotImplementedError


def make_result(store_key: str, cfg: dict, status: Status, **kw) -> CheckResult:
    """Crea un CheckResult rellenando los metadatos comunes desde el config."""
    return CheckResult(
        store_key=store_key,
        store_name=cfg.get("name", store_key),
        country=cfg.get("country", "—"),
        url=cfg.get("url", ""),
        currency=cfg.get("currency"),
        status=status,
        **kw,
    )


def text_has_any(text: str, keywords: list[str]) -> Optional[str]:
    """Devuelve la primera keyword (case-insensitive) presente en el texto, o None."""
    low = text.lower()
    for kw in keywords or []:
        if kw and kw.lower() in low:
            return kw
    return None


def classify_text(text: str, detect: dict) -> Status:
    """Clasifica un bloque de texto según las keywords del config.

    Precedencia: PREORDER > OUT_OF_STOCK > AVAILABLE. Ante duda -> OUT_OF_STOCK
    (nunca AVAILABLE sin señal positiva explícita), para cero falsos positivos.
    """
    preorder_kw = detect.get("preorder_keywords", [
        "preventa", "próximamente", "proximamente", "backorder", "backordered",
        "pre-order", "preorder", "coming soon",
    ])
    unavailable_kw = detect.get("unavailable_keywords", [])
    available_kw = detect.get("available_keywords", [])

    if text_has_any(text, preorder_kw):
        return Status.PREORDER
    if text_has_any(text, unavailable_kw):
        return Status.OUT_OF_STOCK
    if text_has_any(text, available_kw):
        return Status.AVAILABLE
    return Status.OUT_OF_STOCK
