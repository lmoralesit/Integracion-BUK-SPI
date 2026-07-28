"""
Suite de Pruebas End-to-End (E2E) - Webhook BUK con Validación HMAC SHA-256.
Simula el disparo en tiempo real desde BUK hacia la API local de Staging.
"""

import asyncio
import hashlib
import hmac
import json
import logging
import httpx

from app.config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | [TEST-E2E] | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("TEST_WEBHOOK")

API_URL = f"http://127.0.0.1:{settings.APP_PORT}/api/v1/buk/employee"
WEBHOOK_SECRET = settings.BUK_WEBHOOK_SECRET


async def simular_evento_buk(employee_id: int, event_type: str = "employee_create"):
    """
    Construye el payload JSON, calcula la firma criptográfica HMAC-SHA256 en cabecera
    y realiza la solicitud HTTP POST asíncrona hacia el endpoint de escucha activa.
    """
    payload_dict = {
        "data": {
            "employee_id": employee_id,
            "event_type": event_type,
            "date": "2026-07-28",
            "tenant_url": "https://alfonzorivas.buk.co"
        }
    }
    
    # Serialización canónica sin alterar los caracteres ASCII para asegurar precisión en el hash
    payload_bytes = json.dumps(payload_dict, ensure_ascii=False).encode("utf-8")
    
    # Mandamiento DevSecOps #4: Criptografía HMAC-SHA256 idéntica al estándar de BUK
    firma_hmac = hmac.new(
        key=WEBHOOK_SECRET.encode("utf-8"),
        msg=payload_bytes,
        digestmod=hashlib.sha256
    ).hexdigest()
    
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-Buk-Signature": firma_hmac
    }
    
    logger.info("=" * 65)
    logger.info("🚀 DISPARANDO EVENTO WEBHOOK BUK -> SPI")
    logger.info("   • Empleado BUK ID : %s", employee_id)
    logger.info("   • Tipo de Evento  : %s", event_type)
    logger.info("   • Firma HMAC      : %s... (truncada por seguridad)", firma_hmac[:16])
    logger.info("   • Endpoint Destino: %s", API_URL)
    logger.info("=" * 65)
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(API_URL, content=payload_bytes, headers=headers)
            
            logger.info("📡 Status Code HTTP Respuesta: %s", response.status_code)
            
            if response.status_code == 202:
                logger.info("✅ WEBHOOK ACEPTADO (202 Accepted). Evento persistido exitosamente en ODS.")
                logger.info("📦 Body de Respuesta: %s", response.json())
                logger.info("👉 Entra en http://localhost:8000/admin/dashboard para ver el estatus transaccional.")
            elif response.status_code == 403:
                logger.error("❌ RECHAZO DE SEGURIDAD (403 Forbidden). La firma criptográfica HMAC no coincide.")
            elif response.status_code == 422:
                logger.error("❌ ERROR DE VALIDACIÓN PYDANTIC (422 Unprocessable Entity): %s", response.text)
            else:
                logger.warning("⚠️ Respuesta no esperada del servidor: %s", response.text)
                
    except httpx.ConnectError:
        logger.error("❌ Error de Conexión: No se pudo conectar a %s. ¿Está corriendo Uvicorn en el puerto 8000?", API_URL)
    except Exception as e:
        logger.error("❌ Error inesperado durante la ejecución del test: %s", str(e))


async def main():
    logger.info("INICIANDO SUITE DE PRUEBAS E2E DEVSECOPS - INTEGRACIÓN BUK-SPI")
    
    # Prueba 1: Ingreso Estándar (Esperado: Status Flag 1)
    await simular_evento_buk(employee_id=13904, event_type="employee_create")
    
    logger.info("⏳ Esperando 6 segundos para permitir que el Worker en segundo plano procese la cola ODS...")
    await asyncio.sleep(6)
    
    # Prueba 2: Simulación de Cédula Pre-existente con Contrato Abierto (RF-05) (Esperado: Flag 4)
    logger.info("\n" + "-" * 65)
    logger.info("🧪 INICIANDO PRUEBA DE SALVAGUARDA: PRE-EXISTENCIA LABORAL (RF-05)")
    logger.info("-" * 65)
    await simular_evento_buk(employee_id=99999, event_type="employee_create")
    
    logger.info("⏳ Esperando 6 segundos para el procesamiento final del segundo evento...")
    await asyncio.sleep(6)
    
    logger.info("🏁 SUITE DE PRUEBAS FINALIZADA. Revisa el Panel de Administración Visual para confirmar resultados.")


if __name__ == "__main__":
    asyncio.run(main())