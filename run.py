# run.py
import logging
import os
import sys
from pathlib import Path
import uvicorn

# 1. Configuración de Logging Seguro (Sin PII ni Secretos en Claro)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | [%(name)s] | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("DevSecOps.Launcher")

def validate_environment() -> None:
    """
    Mandamiento 1 (Security by Design):
    Valida la existencia del archivo de variables de entorno antes de iniciar.
    Falla de forma segura (Fail-Secure) si el entorno no está preparado.
    """
    env_path = Path(".env")
    if not env_path.exists():
        logger.critical("🚨 ARCHIVO .env NO ENCONTRADO. Abortando arranque por seguridad (Fail-Secure).")
        logger.error("Asegúrate de haber configurado los secretos desde variables de entorno o archivo .env.")
        sys.exit(1)
    
    logger.info("🔒 Entorno validado correctamente. Secretos no expuestos en logs.")

def main() -> None:
    validate_environment()
    
    # Determinar entorno (Por defecto 'development' por seguridad)
    env = os.getenv("APP_ENV", "development").lower()
    is_dev = env == "development"
    
    # 🚨 Regla DevSecOps: Si es desarrollo, NUNCA abrir a 0.0.0.0
    host = "127.0.0.1" if is_dev else os.getenv("SERVER_HOST", "0.0.0.0")
    port = int(os.getenv("SERVER_PORT", 8000))
    
    logger.info(f"🚀 Iniciando Integración ETL BUK-SPI en modo: [{env.upper()}]")
    logger.info(f"🛡️ Binding de red configurado en: http://{host}:{port}")
    
    if is_dev and host == "0.0.0.0":
        logger.warning("⚠️ ALERTA: Ejecutando en modo DEV abierto a todas las interfaces (0.0.0.0). Usa con precaución.")

    try:
        uvicorn.run(
            app="app.main:app",       # Ruta correcta al módulo principal
            host=host,
            port=port,
            reload=is_dev,            # Reload asíncrono solo en desarrollo
            workers=1 if is_dev else int(os.getenv("WORKERS_COUNT", 4)),
            log_level="info",
            access_log=True,
            server_header=False       # Seguridad: Ocultar cabecera 'Server: uvicorn' frente a fingerprinting
        )
    except Exception as e:
        logger.critical(f"🔥 Error crítico en el ciclo de ejecución del servidor: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()