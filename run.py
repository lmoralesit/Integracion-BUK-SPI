# run.py
import logging
import os
import sys
from pathlib import Path
import uvicorn

# ---------------------------------------------------------------------------
# ANCLAJE ABSOLUTO DE RUTAS (Prevención de Workspace Drift y Path Traversal)
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"
APP_MODULE = "app.main:app"

# Configuración de Logging Seguro (Mandamiento #5)
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
    Valida la existencia del archivo .env mediante rutas absolutas.
    Falla de forma segura (Fail-Secure) si el entorno no está preparado.
    """
    if not ENV_PATH.exists():
        logger.critical(f"🚨 ARCHIVO .env NO ENCONTRADO EN RUTA ABSOLUTA: [{ENV_PATH}]")
        logger.error("Abortando arranque por seguridad. Sincroniza tus variables de entorno locales.")
        sys.exit(1)
    
    logger.info(f"🔒 Entorno validado en ruta absoluta: [{BASE_DIR}]. Secretos blindados.")

def main() -> None:
    validate_environment()
    
    env = os.getenv("APP_ENV", "development").lower()
    is_dev = env == "development"
    
    # 🚨 Mandamiento DevSecOps: Prohibido bindear a 0.0.0.0 en desarrollo local
    host = "127.0.0.1" if is_dev else os.getenv("APP_HOST", "0.0.0.0")
    port = int(os.getenv("APP_PORT", 8000))
    
    logger.info(f"🚀 Iniciando Integración ETL BUK-SPI en modo: [{env.upper()}]")
    logger.info(f"🛡️ Binding de red configurado en: http://{host}:{port}")

    try:
        # Al pasar reload_dirs de forma explícita y absoluta, evitamos que WatchFiles
        # evalúe rutas vacías ('') que rompen los escáneres en Windows.
        uvicorn.run(
            app=APP_MODULE,
            host=host,
            port=port,
            reload=is_dev,
            reload_dirs=[str(BASE_DIR / "app")] if is_dev else None,
            workers=1 if is_dev else int(os.getenv("WORKERS_COUNT", 2)),
            log_level="info",
            access_log=True,
            server_header=False  # Seguridad: Ocultar fingerprint del servidor
        )
    except Exception as e:
        logger.critical(f"🔥 Error crítico en el ciclo de ejecución del servidor: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()