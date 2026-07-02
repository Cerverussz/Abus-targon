"""Detector "manual": tiendas que no se pueden verificar automáticamente.

Para sitios con anti-bot que el scraper disponible no supera (p. ej. LordGun/
Cloudflare y Abus/Akamai en plan gratuito), no gastamos llamadas: se devuelve
ERROR directamente y, si la tienda tiene ``manual_fallback: true``, el checker
manda un recordatorio por Telegram para revisarla a mano.
"""
from __future__ import annotations

from ..models import CheckResult, Status
from .base import Detector, make_result


class ManualDetector(Detector):
    method = "manual"

    def check(self, store_key: str, cfg: dict) -> CheckResult:
        return make_result(
            store_key, cfg, Status.ERROR,
            error="revisión manual: sin verificación automática (anti-bot)",
        )
