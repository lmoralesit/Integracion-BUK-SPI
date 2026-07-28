"""
Punto de entrada principal de la aplicación ETL BUK-SPI.

Instancia la aplicación FastAPI, registra los routers y configura
el logging y los eventos de inicio/cierre.
"""

import asyncio
import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import settings
from app.api.endpoints.webhook import router as webhook_router
from app.api.endpoints.admin import router as admin_router
from app.services.worker import ETLWorker

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ──────────────────────────────────────────────
# Configuración de Logging
# ──────────────────────────────────────────────
logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# Lifespan (eventos de inicio y cierre)
# ──────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Gestiona los eventos de inicio y cierre de la aplicación."""
    # ── Startup ──
    logger.info("=" * 60)
    logger.info("[START] Iniciando %s v%s", settings.APP_NAME, settings.APP_VERSION)
    logger.info("=" * 60)
    logger.info("Host: %s | Puerto: %s", settings.APP_HOST, settings.APP_PORT)
    logger.info("Debug: %s", settings.DEBUG)
    logger.info("SQL Server: %s/%s", settings.SQLSERVER_HOST, settings.SQLSERVER_DATABASE)
    logger.info("Oracle: %s/%s (Mock: %s)", settings.ORACLE_HOST, settings.ORACLE_SERVICE_NAME, settings.ORACLE_MOCK)
    logger.info("BUK API: %s", settings.BUK_API_BASE_URL)
    logger.info("=" * 60)

    # Verificar conectividad de base de datos Staging al arrancar (Fail-Fast DevSecOps)
    from app.core.db import verify_db_connection_resilient
    import sys
    
    if not verify_db_connection_resilient():
        logger.critical("🛑 Deteniendo arranque de la interfaz ETL BUK-SPI por imposibilidad de conectar a Staging.")
        sys.exit(1)

    # Iniciar worker en segundo plano
    worker = ETLWorker(polling_interval=5.0)
    worker_task = asyncio.create_task(worker.start())

    yield

    # ── Shutdown ──
    logger.info("[STOP] Cerrando %s...", settings.APP_NAME)
    worker.stop()
    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        pass


# ──────────────────────────────────────────────
# Instancia de la aplicación FastAPI
# ──────────────────────────────────────────────
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description=(
        "API de integración ETL entre BUK (RRHH en la nube) y SPI/Infocent "
        "(sistema de nómina local). Recibe webhooks de BUK en tiempo real, "
        "transforma los datos según reglas de negocio y los carga en Oracle."
    ),
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)


# ──────────────────────────────────────────────
# Registro de Routers
# ──────────────────────────────────────────────
app.include_router(webhook_router, prefix="/api/v1", tags=["BUK Webhook"])
app.include_router(admin_router, prefix="/admin", tags=["Administración Visual"])


# ──────────────────────────────────────────────
# Endpoint de Health Check
# ──────────────────────────────────────────────
@app.get(
    "/health",
    tags=["Sistema"],
    summary="Verificar estado de la API",
)
async def health_check():
    """Retorna el estado de salud de la API."""
    return {
        "status": "healthy",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
    }


# ──────────────────────────────────────────────
# Ejecución directa con Uvicorn
# ──────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.APP_HOST,
        port=settings.APP_PORT,
        reload=settings.DEBUG,
    )
