"""
Script de Diagnóstico: Extracción Saliente desde BUK API y Transformación DevSecOps.
"""
import asyncio
import logging
from app.services.buk_client import BukAPIClient
from app.utils.transformers import (
    limpiar_cedula,
    truncar_codigo_cargo,
    format_spi_position,
    formatear_rif,
    sanitizar_nombre
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s | [API-TEST] | %(levelname)s | %(message)s")
logger = logging.getLogger("API_TEST")

async def probar_extraccion_real(employee_id_buk: str):
    logger.info("=" * 65)
    logger.info(f"🌐 Conectando a BUK API para extraer ficha ID: {employee_id_buk}...")
    logger.info("=" * 65)
    
    cliente = BukAPIClient()
    
    try:
        # Petición GET con reintentos exponenciales asíncronos
        data = await cliente.get_employee_detail(employee_id_buk)
        
        if not data:
            logger.error("❌ La API no devolvió datos. Verifica que el ID exista en BUK y el Token sea válido.")
            return

        logger.info("✅ Ficha recibida con éxito desde BUK Cloud.")
        
        # Extracción de bloques de información[cite: 4, 8]
        attrs = data.get("custom_attributes", {}) or {}
        trabajo = data.get("current_job", {}) or {}
        role_info = trabajo.get("role", {}) or {}
        area_info = trabajo.get("area", {}) or {}

        # Transformaciones DevSecOps[cite: 6, 8]
        cedula_cruda = data.get("document_number") or data.get("rut") or ""
        cedula_limpia = limpiar_cedula(cedula_cruda)
        rif_limpio = formatear_rif(attrs.get("tipo_rif"), attrs.get("RIF") or cedula_cruda)
        nombre_limpio = sanitizar_nombre(f"{data.get('first_name', '')} {data.get('surname', '')}")
        cargo_depurado = truncar_codigo_cargo(role_info.get("id") or attrs.get("codigo_cargo"))
        puesto_spi = format_spi_position(area_info.get("name", "GENERAL"), role_info.get("name", "OPERARIO"))

        # Mostrar resultados para auditoría[cite: 6, 8]
        logger.info("-" * 50)
        logger.info("🔬 RESULTADO DE LA SANITIZACIÓN PARA ORACLE SPI:")
        logger.info(f" 🔹 Colaborador     : {nombre_limpio}")
        logger.info(f" 🔹 Cédula / RIF    : CI: {cedula_limpia} | RIF: {rif_limpio}")
        logger.info(f" 🔹 Código Cargo    : '{cargo_depurado}' (Trunco sin '.0')")
        logger.info(f" 🔹 Puesto SPI      : '{puesto_spi}' (Max 36 chars - Len: {len(puesto_spi)})")
        logger.info(f" 🔹 Empresa Derivada: '{attrs.get('codigo_empresa', 'D6')}'")
        logger.info("-" * 50)

    except Exception as e:
        logger.error(f"❌ Fallo crítico de conexión a BUK API: {e}")

if __name__ == "__main__":
    # IMPORTANTE: Reemplaza "13904" por el ID o RUT de un empleado activo en tu portal BUK
    asyncio.run(probar_extraccion_real("13904"))