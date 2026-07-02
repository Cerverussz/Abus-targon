"""Detector vía servicio de scraping (método "scraper").

Para tiendas que bloquean al navegador headless con anti-bot (Cloudflare,
Akamai...), enrutamos la petición a un servicio externo que renderiza JS y
resuelve el challenge, devolviendo el HTML final. Ese HTML se parsea con la
misma lógica de keywords/selectores que el método "static".

Agnóstico de proveedor: ``SCRAPER_PROVIDER`` elige el formato de la petición
(scraperapi | zenrows | scrapingbee | custom) y ``SCRAPER_API_KEY`` la clave.
Solo se usa donde hace falta (3 corridas/día), para no gastar créditos.
"""
from __future__ import annotations

import json
import logging
import os
import time

import httpx
from bs4 import BeautifulSoup

from ..models import CheckResult, Status
from .base import Detector, classify_text, is_antibot, make_result
from .static_store import _parse_price, _scope_text

logger = logging.getLogger(__name__)

# El render remoto puede tardar; damos margen amplio (solo 3 corridas/día).
SCRAPER_TIMEOUT = int(os.getenv("SCRAPER_TIMEOUT", "90"))
SCRAPER_RETRIES = int(os.getenv("SCRAPER_RETRIES", "2"))


def _build_request(target_url: str, detect: dict) -> tuple[str, dict]:
    """Construye (base_url, params) según el proveedor configurado en el entorno.

    ``scraper_hard`` (detect) activa el modo reforzado del proveedor, necesario
    para anti-bot duro (Cloudflare/Akamai). Cuesta más créditos, por eso es
    opt-in por tienda. ``scraper_params`` permite añadir/forzar parámetros
    arbitrarios (escape hatch, agnóstico de proveedor).
    """
    key = os.getenv("SCRAPER_API_KEY")
    if not key:
        raise RuntimeError(
            "Falta SCRAPER_API_KEY en el entorno (.env / secret de GitHub)."
        )
    provider = (os.getenv("SCRAPER_PROVIDER") or "scraperapi").lower()
    country = detect.get("scraper_country")
    hard = bool(detect.get("scraper_hard", False))

    if provider == "scraperapi":
        base = "https://api.scraperapi.com/"
        params = {"api_key": key, "url": target_url, "render": "true"}
        if country:
            params["country_code"] = country
        if hard:
            params["ultra_premium"] = "true"  # anti-bot reforzado de ScraperAPI

    elif provider == "zenrows":
        base = "https://api.zenrows.com/v1/"
        params = {
            "apikey": key, "url": target_url,
            "js_render": "true", "antibot": "true",
        }
        if country:
            params["proxy_country"] = country
        if hard:
            params["premium_proxy"] = "true"

    elif provider == "scrapingbee":
        base = "https://app.scrapingbee.com/api/v1/"
        params = {
            "api_key": key, "url": target_url,
            "render_js": "true", "stealth_proxy": "true",
        }
        if country:
            params["country_code"] = country
        if hard:
            params["premium_proxy"] = "true"

    elif provider == "custom":
        base = os.getenv("SCRAPER_BASE_URL")
        if not base:
            raise RuntimeError("SCRAPER_PROVIDER=custom requiere SCRAPER_BASE_URL.")
        params = json.loads(os.getenv("SCRAPER_PARAMS") or "{}")
        params[os.getenv("SCRAPER_URL_PARAM", "url")] = target_url
        params[os.getenv("SCRAPER_KEY_PARAM", "api_key")] = key

    else:
        raise RuntimeError(f"SCRAPER_PROVIDER desconocido: {provider!r}.")

    # Escape hatch: parámetros extra desde el config (fuerzan/añaden lo anterior).
    for k, v in (detect.get("scraper_params") or {}).items():
        params[k] = str(v)
    return base, params


def _fetch_html(store_key: str, base: str, params: dict) -> str:
    """GET al proveedor con reintentos ante 5xx/errores de red; loguea el cuerpo."""
    last_exc: Exception | None = None
    with httpx.Client(timeout=SCRAPER_TIMEOUT, follow_redirects=True) as client:
        for attempt in range(1, SCRAPER_RETRIES + 2):
            try:
                resp = client.get(base, params=params)
                resp.raise_for_status()
                return resp.text
            except httpx.HTTPStatusError as exc:
                code = exc.response.status_code
                body = (exc.response.text or "").strip().replace("\n", " ")[:200]
                logger.warning(
                    "[%s] scraper HTTP %s (intento %d/%d): %s",
                    store_key, code, attempt, SCRAPER_RETRIES + 1, body,
                )
                last_exc = exc
                if code < 500 and code != 429:
                    break  # 4xx (salvo 429) = config/credenciales: no reintentar
            except httpx.HTTPError as exc:
                logger.warning(
                    "[%s] scraper error de red (intento %d/%d): %s",
                    store_key, attempt, SCRAPER_RETRIES + 1, exc,
                )
                last_exc = exc
            if attempt <= SCRAPER_RETRIES:
                time.sleep(2 * attempt)
    raise last_exc if last_exc else RuntimeError("fallo desconocido del scraper")


class ScraperDetector(Detector):
    method = "scraper"

    def check(self, store_key: str, cfg: dict) -> CheckResult:
        detect = cfg.get("detect", {})
        base, params = _build_request(cfg["url"], detect)
        html = _fetch_html(store_key, base, params)

        soup = BeautifulSoup(html, "html.parser")
        page_text = soup.get_text(" ", strip=True)
        title = (soup.title.string if soup.title else "") or ""
        logger.info("[%s] scraper título='%s'", store_key, title.strip()[:120])

        # Si el proveedor no logró pasar el anti-bot, ERROR honesto (no AGOTADO).
        if is_antibot(title, page_text):
            logger.warning("[%s] anti-bot no superado pese al scraper.", store_key)
            return make_result(
                store_key, cfg, Status.ERROR,
                error="bloqueo anti-bot pese al servicio de scraping",
            )

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
