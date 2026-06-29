"""Detector para tiendas Shopify (método "shopify").

Usa los endpoints JSON públicos de Shopify, que exponen ``variant.available``
como dato estructurado y fiable -> cero falsos positivos.

- URL de producto  -> ``<url>.json``            (objeto ``product``)
- URL de colección -> ``<url>/products.json``    (lista ``products``)

Para catálogos colombianos (DSCBike, BiciMarket) que aún no listan el modelo,
se apunta a la colección y se busca ``search_term`` (p. ej. "targon"); si no
aparece -> NOT_LISTED.
"""
from __future__ import annotations

import logging
import re

import httpx

from ..models import CheckResult, Status
from .base import DEFAULT_TIMEOUT, USER_AGENT, Detector, make_result, text_has_any

logger = logging.getLogger(__name__)


def _size_matches(variant: dict, size_keywords: list[str]) -> bool:
    """¿La variante corresponde a la talla M (55–58)?"""
    haystack = " ".join(
        str(variant.get(k, "")) for k in ("title", "option1", "option2", "option3")
    )
    return text_has_any(haystack, size_keywords) is not None


def _price_of(variant: dict) -> float | None:
    raw = variant.get("price")
    if raw is None:
        return None
    try:
        # En products.json el precio suele venir como string "199.00"; en otros
        # endpoints como centavos enteros. Heurística: si es int grande, /100.
        val = float(raw)
        if isinstance(raw, int) and val > 1000:
            val = val / 100.0
        return val
    except (TypeError, ValueError):
        return None


def _color_of(product: dict, variant: dict) -> str | None:
    # Busca una opción cuyo nombre sugiera color.
    options = product.get("options") or []
    for idx, opt in enumerate(options, start=1):
        name = (opt.get("name") if isinstance(opt, dict) else str(opt)) or ""
        if any(c in name.lower() for c in ("color", "colour", "colore")):
            return variant.get(f"option{idx}")
    return None


def _product_matches(product: dict, search_term: str, mips_required: bool) -> bool:
    title = (product.get("title") or "").lower()
    handle = (product.get("handle") or "").lower()
    text = f"{title} {handle}"
    if search_term and search_term.lower() not in text:
        return False
    if mips_required and "mips" not in text:
        return False
    return True


def _evaluate_product(store_key: str, cfg: dict, product: dict) -> CheckResult:
    detect = cfg.get("detect", {})
    size_keywords = detect.get("size_keywords", ["M", "55", "55-58", "medium"])
    variants = product.get("variants") or []

    matching = [v for v in variants if _size_matches(v, size_keywords)]
    # Si no hay variantes de talla (producto sin tallas) usamos todas.
    candidates = matching or variants
    if not candidates:
        return make_result(store_key, cfg, Status.OUT_OF_STOCK)

    available = next((v for v in candidates if v.get("available")), None)
    chosen = available or candidates[0]
    status = Status.AVAILABLE if available else Status.OUT_OF_STOCK
    return make_result(
        store_key,
        cfg,
        status,
        price=_price_of(chosen) if status == Status.AVAILABLE else _price_of(chosen),
        color=_color_of(product, chosen),
    )


class ShopifyDetector(Detector):
    method = "shopify"

    def check(self, store_key: str, cfg: dict) -> CheckResult:
        url = cfg["url"].rstrip("/")
        detect = cfg.get("detect", {})
        is_collection = "/collections/" in url and "/products/" not in url
        headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}

        with httpx.Client(
            headers=headers, timeout=DEFAULT_TIMEOUT, follow_redirects=True
        ) as client:
            if is_collection:
                return self._check_collection(client, store_key, cfg, url, detect)
            return self._check_product(client, store_key, cfg, url)

    def _check_product(self, client, store_key, cfg, url) -> CheckResult:
        resp = client.get(f"{url}.json")
        resp.raise_for_status()
        product = resp.json().get("product")
        if not product:
            return make_result(store_key, cfg, Status.NOT_LISTED)
        return _evaluate_product(store_key, cfg, product)

    def _check_collection(self, client, store_key, cfg, url, detect) -> CheckResult:
        search_term = detect.get("search_term", "targon")
        mips_required = bool(detect.get("require_mips", True))
        resp = client.get(f"{url}/products.json", params={"limit": 250})
        resp.raise_for_status()
        products = resp.json().get("products", [])
        match = next(
            (p for p in products if _product_matches(p, search_term, mips_required)),
            None,
        )
        if not match:
            logger.info(
                "[%s] '%s' no aparece en la colección (%d productos).",
                store_key, search_term, len(products),
            )
            return make_result(store_key, cfg, Status.NOT_LISTED)
        return _evaluate_product(store_key, cfg, match)
