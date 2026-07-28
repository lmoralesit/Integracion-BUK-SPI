"""
Módulo de Configuración Centralizada (app.config).

Re-exporta la instancia singleton `settings` desde app.core.config para retrocompatibilidad.
"""

from app.core.config import settings, Settings

__all__ = ["settings", "Settings"]
