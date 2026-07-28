"""
Conector Resiliente a SQL Server Staging (app.database.sql_server).
Implementa operaciones DML transaccionales e idempotentes con soporte
estricto para Autenticación Integrada de Windows (Zero-Passwords) y SQL Auth.
"""
import logging
import pyodbc
from app.core.config import settings

logger = logging.getLogger("ETL_BUK_SPI")

def get_sqlserver_connection() -> pyodbc.Connection:
    """
    Establece y retorna conexión ODBC hacia SQL Server Staging.
    Fuerza Autenticación Integrada si SQLSERVER_USER es 'windows', 'trusted' o vacío.
    """
    usuario = settings.SQLSERVER_USER.strip().lower()
    
    # Mandamiento #1: Mínimo Privilegio / Zero-Passwords mediante Windows Auth
    if not usuario or usuario in ("windows", "trusted", "integrated"):
        auth_str = "Trusted_Connection=yes;"
        logger.debug("[SQLSERVER] Conectando mediante Autenticación Integrada de Windows...")
    else:
        pwd = settings.SQLSERVER_PASSWORD.get_secret_value()
        auth_str = f"UID={settings.SQLSERVER_USER};PWD={pwd};"
        logger.debug("[SQLSERVER] Conectando mediante SQL Auth (Usuario: %s)...", settings.SQLSERVER_USER)

    conn_str = (
        f"DRIVER={settings.SQLSERVER_DRIVER};"
        f"SERVER={settings.SQLSERVER_HOST};"
        f"DATABASE={settings.SQLSERVER_DATABASE};"
        f"{auth_str}"
        "TrustServerCertificate=yes;"
    )
    
    try:
        # Timeout agresivo (8s) para no colapsar hilos asíncronos de FastAPI ante intermitencias
        return pyodbc.connect(conn_str, timeout=8)
    except pyodbc.Error as exc:
        logger.error("[SQLSERVER ERROR] Fallo crítico al conectar a Staging (%s): %s", settings.SQLSERVER_HOST, str(exc))
        raise exc

def get_next_atomic_ficha(conn: pyodbc.Connection, empresa_code: str = "D6") -> str:
    """
    Mandamiento #3 & RF-01: Reserva y autogenera el correlativo corporativo único
    de ficha (ej. F101) de forma atómica (UPDLOCK, ROWLOCK) evitando race conditions.
    """
    cursor = conn.cursor()
    try:
        cursor.execute("""
            UPDATE dbo.ETL_CORRELATIVOS WITH (UPDLOCK, ROWLOCK)
            SET u_ficha = u_ficha + 1
            OUTPUT INSERTED.u_ficha
            WHERE empresa_id = ?;
        """, (empresa_code,))
        row = cursor.fetchone()
        
        # Fallback a semilla DEFAULT si la empresa no está registrada explícitamente
        if not row:
            cursor.execute("""
                UPDATE dbo.ETL_CORRELATIVOS WITH (UPDLOCK, ROWLOCK)
                SET u_ficha = u_ficha + 1
                OUTPUT INSERTED.u_ficha
                WHERE empresa_id = 'DEFAULT';
            """)
            row = cursor.fetchone()

        if not row:
            raise ValueError("No se encontraron registros de semillas en la tabla ETL_CORRELATIVOS.")

        nueva_ficha = f"F{row[0]}"
        conn.commit()  # Consolidamos la transacción de reserva atómica
        logger.info("[CORRELATIVO ATÓMICO] Ficha reservada corporativamente: %s", nueva_ficha)
        return nueva_ficha
    except Exception as exc:
        conn.rollback()
        logger.error("[CORRELATIVO ERROR] Fallo al reservar correlativo atómico: %s", str(exc))
        raise exc
    finally:
        cursor.close()