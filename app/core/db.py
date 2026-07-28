"""
Gestor de Conexiones e Inyección de Dependencias (app.core.db).
Provee el generador `get_staging_db` para FastAPI asegurando cierre de recursos.
"""
import logging
from typing import Generator
import pyodbc
from fastapi import HTTPException, status
from app.database.sql_server import get_sqlserver_connection

logger = logging.getLogger("ETL_BUK_SPI")

def get_staging_db() -> Generator[pyodbc.Connection, None, None]:
    """
    Inyección de dependencia para endpoints FastAPI. Abre conexión a SQL Server Staging
    y asegura su liberación en el bloque finally, capturando errores de login limpiamente.
    """
    conn = None
    try:
        conn = get_sqlserver_connection()
        yield conn
    except pyodbc.Error as exc:
        logger.error("[DB DEPENDENCY ERROR] No se pudo inyectar la conexión a Staging: %s", str(exc))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Servicio de base de datos Staging no disponible o falló la autenticación."
        )
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass