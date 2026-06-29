"""Detector para páginas estáticas (método "static"): httpx + BeautifulSoup."""
from __future__ import annotations

import logging
import re

import httpx
from bs4 import BeautifulSoup

from ..models import CheckResult, Status
from .base import (
    DEFAULT_TIMEOUT,
    USER_AGENT,
    Detector,
    classify_text,
    make_result,
    text_has_any,
)

logger = logging.getLogger(__name__)

_PRICE_RE = re.compile(r"(\d[\d.\s]*[.,]\d{2}|\d[\d.,]*)")


def _parse_price(text: str) -> float | None:
    if not text:
        return None
    m = _PRICE_RE.search(text.replace("\xa0", " "))
    if not m:
        return None
    raw = m.group(1).strip().replace(" ", "")
    # Normaliza separadores: si hay coma decimal estilo europeo (1.234,56).
    if "," in raw and "." in raw:
        raw = raw.replace(".", "").replace(",", ".")
    elif "," in raw:
        raw = raw.replace(",", ".")
    try:
        return float(raw)
    except ValueError:
        return None


def _scope_text(soup: BeautifulSoup, detect: dict) -> str:
    """Devuelve el texto sobre el que clasificar.

    Si hay ``size_selector``, intenta acotar al bloque de la talla M; si no,
    usa el texto de toda la página.
    """
    size_selector = detect.get("size_selector")
    size_keywords = detect.get("size_keywords", ["M", "55", "55-58", "medium"])
    if size_selector:
        nodes = soup.select(size_selector)
        for node in nodes:
            if text_has_any(node.get_text(" ", strip=True), size_keywords):
                # Texto del nodo + su contenedor cercano para captar el estado.
                parent = node.find_parent() or node
                return parent.get_text(" ", strip=True)
    return soup.get_text(" ", strip=True)


class StaticDetector(Detector):
    method = "static"

    def check(self, store_key: str, cfg: dict) -> CheckResult:
        detect = cfg.get("detect", {})
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
        }
        with httpx.Client(
            headers=headers, timeout=DEFAULT_TIMEOUT, follow_redirects=True
        ) as client:
            resp = client.get(cfg["url"])
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")

        # ¿El producto aparece siquiera? (defensa contra 404 suaves).
        size_keywords = detect.get("size_keywords", ["M", "55", "55-58", "medium"])
        page_text = soup.get_text(" ", strip=True)
        if detect.get("require_mips", False) and "mips" not in page_text.lower():
            return make_result(store_key, cfg, Status.NOT_LISTED)

        scoped = _scope_text(soup, detect)
        status = classify_text(scoped, detect)

        price = None
        color = None
        if status == Status.AVAILABLE:
            price_selector = detect.get("price_selector")
            if price_selector:
                node = soup.select_one(price_selector)
                if node:
                    price = _parse_price(node.get_text(" ", strip=True))
            color = detect.get("color")

        return make_result(store_key, cfg, status, price=price, color=color)
