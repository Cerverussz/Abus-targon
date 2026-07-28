"""Interfaz base y utilidades compartidas por los detectores."""
from __future__ import annotations

import logging
import re
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


# Mínimo de caracteres para considerar que sí leímos la página. Por debajo de
# esto (página en blanco, JS que no renderizó, muro de cookies vacío) no hay
# nada que clasificar: es ERROR, no AGOTADO ni NO LISTADO.
MIN_READABLE_CHARS = 200


def is_unreadable(text: str, min_chars: int = MIN_READABLE_CHARS) -> bool:
    """True si la página no trae contenido suficiente para decidir nada."""
    return len((text or "").strip()) < min_chars


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


# Longitud máxima de una keyword de talla que se compara como palabra completa.
# "M" o "55" como subcadena aparecen dentro de "Small", "Medium" o "55-58 cm".
SHORT_SIZE_KEYWORD_LEN = 2


def _whole_word_re(keyword: str) -> re.Pattern:
    return re.compile(rf"\b{re.escape(keyword)}\b", re.IGNORECASE)


def size_matches(text: str, keywords: list[str]) -> Optional[str]:
    """Como ``text_has_any``, pero exigiendo palabra completa en tallas cortas.

    Buscar la talla "M" como subcadena da falsos positivos en todas partes:
    la 'm' está en "Small", en "Medium" y en "55-58 cm", así que la variante
    equivocada pasaría por M y una S disponible se anunciaría como M
    disponible. Las keywords largas ("55-58", "Medium") siguen comparándose
    como subcadena, que es lo que se quiere para rangos y palabras.
    """
    if not text:
        return None
    low = text.lower()
    for kw in keywords or []:
        kw = (kw or "").strip()
        if not kw:
            continue
        if len(kw) <= SHORT_SIZE_KEYWORD_LEN:
            if _whole_word_re(kw).search(text):
                return kw
        elif kw.lower() in low:
            return kw
    return None


DEFAULT_PREORDER_KEYWORDS = [
    "preventa", "próximamente", "proximamente", "backorder", "backordered",
    "pre-order", "preorder", "coming soon",
]


def state_keywords(detect: dict) -> tuple[list, list, list]:
    """(preventa, agotado, disponible) según el config, con defaults."""
    return (
        detect.get("preorder_keywords", DEFAULT_PREORDER_KEYWORDS),
        detect.get("unavailable_keywords", []),
        detect.get("available_keywords", []),
    )


def has_state_signal(text: str, detect: dict) -> bool:
    """True si el texto ya dice por sí solo si hay stock (o no)."""
    return any(text_has_any(text, kws) for kws in state_keywords(detect))


def classify_text(text: str, detect: dict) -> Status:
    """Clasifica un bloque de texto según las keywords del config.

    Precedencia: PREORDER > OUT_OF_STOCK > AVAILABLE. Ante duda -> OUT_OF_STOCK
    (nunca AVAILABLE sin señal positiva explícita), para cero falsos positivos.
    """
    preorder_kw, unavailable_kw, available_kw = state_keywords(detect)

    if text_has_any(text, preorder_kw):
        return Status.PREORDER
    if text_has_any(text, unavailable_kw):
        return Status.OUT_OF_STOCK
    if text_has_any(text, available_kw):
        return Status.AVAILABLE
    return Status.OUT_OF_STOCK
