"""Detector con navegador (método "playwright") para sitios con JS.

Estrategia anti-falsos-positivos: solo marca AVAILABLE si la opción de talla M
es seleccionable/habilitada *y* el botón de añadir al carrito está habilitado
(o aparece una keyword de disponibilidad), y *no* hay keyword de agotado.
"""
from __future__ import annotations

import logging
import re

from ..models import CheckResult, Status
from .base import (
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
    if "," in raw and "." in raw:
        raw = raw.replace(".", "").replace(",", ".")
    elif "," in raw:
        raw = raw.replace(",", ".")
    try:
        return float(raw)
    except ValueError:
        return None


class PlaywrightDetector(Detector):
    method = "playwright"

    def check(self, store_key: str, cfg: dict) -> CheckResult:
        # Import diferido: Playwright solo es necesario para este método.
        from playwright.sync_api import TimeoutError as PWTimeout
        from playwright.sync_api import sync_playwright

        detect = cfg.get("detect", {})
        url = cfg["url"]
        size_keywords = detect.get("size_keywords", ["M", "55", "55-58", "medium"])
        wait_ms = int(detect.get("wait_ms", 4000))

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                context = browser.new_context(
                    user_agent=USER_AGENT,
                    locale="es-ES",
                    viewport={"width": 1366, "height": 900},
                )
                page = context.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=45000)
                try:
                    page.wait_for_load_state("networkidle", timeout=15000)
                except PWTimeout:
                    pass  # algunos sitios nunca quedan idle; seguimos igual.
                page.wait_for_timeout(wait_ms)

                # Diagnóstico: nos dice si la URL es válida o redirige (útil
                # cuando una tienda devuelve NOT_LISTED inesperadamente).
                try:
                    logger.info(
                        "[%s] título='%s' url_final=%s",
                        store_key, (page.title() or "")[:120], page.url,
                    )
                except Exception:  # noqa: BLE001
                    pass

                full_text = (page.inner_text("body") or "")
                if detect.get("require_mips", False) and "mips" not in full_text.lower():
                    return make_result(store_key, cfg, Status.NOT_LISTED)

                status = self._evaluate(page, cfg, detect, size_keywords, full_text)

                price = None
                color = detect.get("color")
                if status == Status.AVAILABLE:
                    price = self._read_price(page, detect)
                return make_result(store_key, cfg, status, price=price, color=color)
            finally:
                browser.close()

    def _evaluate(self, page, cfg, detect, size_keywords, full_text) -> Status:
        from playwright.sync_api import TimeoutError as PWTimeout

        # Keywords globales primero: preventa/agotado mandan.
        preorder_kw = detect.get("preorder_keywords", [
            "preventa", "próximamente", "proximamente", "backorder",
            "backordered", "pre-order", "preorder", "coming soon",
        ])
        if text_has_any(full_text, preorder_kw):
            return Status.PREORDER

        size_selector = detect.get("size_selector")
        addtocart_selector = detect.get("add_to_cart_selector")

        # 1) Intentar localizar y seleccionar la opción de talla M.
        m_selectable = None
        if size_selector:
            try:
                options = page.query_selector_all(size_selector)
            except Exception:  # noqa: BLE001
                options = []
            for opt in options:
                try:
                    label = (opt.inner_text() or "").strip()
                except Exception:  # noqa: BLE001
                    label = ""
                if not text_has_any(label, size_keywords):
                    continue
                disabled = self._is_disabled(opt)
                m_selectable = not disabled
                if m_selectable:
                    try:
                        opt.click(timeout=3000)
                        page.wait_for_timeout(800)
                    except Exception:  # noqa: BLE001
                        pass
                break
            if m_selectable is False:
                return Status.OUT_OF_STOCK

        # 2) Releer texto tras seleccionar la talla.
        try:
            text_after = page.inner_text("body") or full_text
        except Exception:  # noqa: BLE001
            text_after = full_text

        unavailable_kw = detect.get("unavailable_keywords", [])
        if text_has_any(text_after, unavailable_kw):
            return Status.OUT_OF_STOCK

        # 3) Botón de añadir al carrito habilitado = señal positiva fuerte.
        if addtocart_selector:
            btn = page.query_selector(addtocart_selector)
            if btn is not None and not self._is_disabled(btn):
                return Status.AVAILABLE
            if btn is not None and self._is_disabled(btn):
                return Status.OUT_OF_STOCK

        # 4) Fallback: clasificación por keywords (nunca AVAILABLE sin señal).
        if m_selectable is True:
            return Status.AVAILABLE
        return classify_text(text_after, detect)

    @staticmethod
    def _is_disabled(handle) -> bool:
        try:
            if handle.get_attribute("disabled") is not None:
                return True
            aria = handle.get_attribute("aria-disabled")
            if aria and aria.lower() == "true":
                return True
            cls = (handle.get_attribute("class") or "").lower()
            if any(tok in cls for tok in ("disabled", "soldout", "sold-out", "unavailable", "out-of-stock")):
                return True
            if not handle.is_enabled():
                return True
        except Exception:  # noqa: BLE001
            return False
        return False

    @staticmethod
    def _read_price(page, detect) -> float | None:
        selector = detect.get("price_selector")
        if not selector:
            return None
        node = page.query_selector(selector)
        if not node:
            return None
        try:
            return _parse_price(node.inner_text())
        except Exception:  # noqa: BLE001
            return None
