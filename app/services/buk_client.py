"""
Cliente REST Asíncrono para la API de BUK (app.services.buk_client).
Implementa reintentos automáticos y backoff ante fallos de red o errores HTTP 5xx.
"""
import asyncio
import logging
import httpx
from typing import Dict, Any, Optional
from app.core.config import settings

logger = logging.getLogger("ETL_BUK_SPI")

class BukAPIClient:
    def __init__(self, max_retries: int = 2, base_delay: float = 1.5):
        self.base_url = settings.BUK_API_BASE_URL.rstrip("/")
        raw_token = settings.BUK_API_TOKEN
        self.token = raw_token.get_secret_value() if hasattr(raw_token, 'get_secret_value') else str(raw_token)
        self.max_retries = max_retries
        self.base_delay = base_delay

    def _get_headers(self) -> Dict[str, str]:
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.token}",
            "auth_token": self.token  # Compatibilidad con API BUK heredada
        }

    async def get_employee_detail(self, employee_id: str | int) -> Dict[str, Any]:
        """
        Consulta la ficha técnica en el endpoint /employees/{id}.
        Mandamiento #2: Resiliencia mediante retries exponenciales asíncronos.
        """
        url = f"{self.base_url}/employees/{employee_id}"
        headers = self._get_headers()

        async with httpx.AsyncClient(timeout=15.0) as client:
            for intento in range(1, self.max_retries + 1):
                try:
                    logger.info("[BUK-API] Consultando empleado ID: %s (Intento %d/%d)", employee_id, intento, self.max_retries)
                    response = await client.get(url, headers=headers)
                    
                    if response.status_code >= 500:
                        response.raise_for_status()
                    
                    if response.status_code == 404:
                        logger.warning("[BUK-API] Empleado ID %s no encontrado en BUK (404).", employee_id)
                        return {}

                    response.raise_for_status()
                    data = response.json().get("data", {})
                    return data[0] if isinstance(data, list) and data else data

                except (httpx.RequestError, httpx.HTTPStatusError) as exc:
                    if intento == self.max_retries:
                        logger.error("[BUK-API ERROR] Fallo definitivo al obtener empleado %s tras %d intentos: %s", employee_id, self.max_retries, str(exc))
                        raise exc
                    
                    delay = self.base_delay * (2 ** (intento - 1))
                    logger.warning("[BUK-API RETRY] Error intermitente (%s). Reintentando en %.1fs...", str(exc), delay)
                    await asyncio.sleep(delay)
        return {}

    async def patch_employee_ficha(self, employee_id: str | int, ficha_asignada: str) -> bool:
        """
        Inyecta el correlativo autogenerado en BUK mediante una solicitud PATCH al módulo de Onboarding.
        """
        url = f"{self.base_url}/employees/{employee_id}"
        headers = self._get_headers()
        payload = {
            "code_sheet": ficha_asignada,
            "custom_attributes": {
                "Ficha": ficha_asignada
            }
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            for intento in range(1, self.max_retries + 1):
                try:
                    logger.info("[BUK-API] Parcheando Ficha '%s' en BUK ID: %s (Intento %d)", ficha_asignada, employee_id, intento)
                    response = await client.patch(url, headers=headers, json=payload)
                    response.raise_for_status()
                    logger.info("[BUK-API OK] Ficha '%s' sincronizada exitosamente en BUK.", ficha_asignada)
                    return True
                except (httpx.RequestError, httpx.HTTPStatusError) as exc:
                    if intento == self.max_retries:
                        logger.error("[BUK-API ERROR] No se pudo inyectar la ficha en BUK ID %s: %s", employee_id, str(exc))
                        return False
                    await asyncio.sleep(self.base_delay * (2 ** (intento - 1)))
        return False
