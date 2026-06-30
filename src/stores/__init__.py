"""Registry/factory de detectores por método declarado en el config."""
from __future__ import annotations

from .base import Detector
from .playwright_store import PlaywrightDetector
from .scraper_store import ScraperDetector
from .shopify_store import ShopifyDetector
from .static_store import StaticDetector

_DETECTORS: dict[str, type[Detector]] = {
    ShopifyDetector.method: ShopifyDetector,
    StaticDetector.method: StaticDetector,
    PlaywrightDetector.method: PlaywrightDetector,
    ScraperDetector.method: ScraperDetector,
}


def get_detector(method: str) -> Detector:
    """Instancia el detector para el método dado (p. ej. "shopify")."""
    try:
        cls = _DETECTORS[method]
    except KeyError:
        raise ValueError(
            f"Método de detección desconocido: {method!r}. "
            f"Opciones: {', '.join(sorted(_DETECTORS))}."
        ) from None
    return cls()


__all__ = ["get_detector", "Detector"]
