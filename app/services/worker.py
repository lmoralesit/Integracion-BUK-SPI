"""
Worker Asincrono de Procesamiento en Segundo Plano.

Consulta periodicamente la tabla ETL_AUDIT_LOG en SQL Server para procesar
los webhooks pendientes (status_flag = 0), delegando la ejecucion a etl_engine.
"""

import asyncio
import logging

from app.database.sql_server import get_sqlserver_connection
from app.services.etl_engine import execute_etl_pipeline

logger = logging.getLogger("ETL_BUK_SPI")


class ETLWorker:
    """
    Worker que procesa en segundo plano la cola de webhooks recibidos.
    """

    def __init__(self, polling_interval: float = 5.0):
        self.polling_interval = polling_interval
        self._is_running = False

    async def start(self):
        """Inicia el ciclo continuo del worker (con validación de conectividad Fail-Fast)."""
        from app.core.db import verify_db_connection_resilient
        
        logger.info("[WORKER] Verificando conectividad inicial con SQL Server Staging...")
        if not verify_db_connection_resilient():
            logger.critical("🛑 Deteniendo arranque de la interfaz ETL BUK-SPI por imposibilidad de conectar a Staging.")
            self._is_running = False
            return

        self._is_running = True
        logger.info("[WORKER] Iniciado (intervalo: %.1fs)", self.polling_interval)

        while self._is_running:
            try:
                await self._procesar_pendientes()
            except Exception as e:
                logger.error("[WORKER] Error inesperado en ciclo: %s", e)

            await asyncio.sleep(self.polling_interval)

    def stop(self):
        """Detiene el ciclo del worker."""
        logger.info("[WORKER] Deteniendo...")
        self._is_running = False

    async def _procesar_pendientes(self):
        """
        Lee registros con status_flag = 0 de ETL_AUDIT_LOG y los procesa.
        """
        sql_conn = None
        pendientes = []

        try:
            sql_conn = get_sqlserver_connection()
            cursor = sql_conn.cursor()
            cursor.execute(
                """
                SELECT TOP 10 id, employee_id, event_type
                FROM dbo.ETL_AUDIT_LOG
                WHERE status_flag = 0
                ORDER BY id ASC
                """
            )
            rows = cursor.fetchall()
            cursor.close()

            for row in rows:
                pendientes.append({"audit_id": row[0], "employee_id": row[1], "event_type": row[2]})

        except Exception as e:
            logger.debug("[WORKER] No pudo consultar SQL Server: %s", e)
            return
        finally:
            if sql_conn:
                try:
                    sql_conn.close()
                except Exception:
                    pass

        if not pendientes:
            return

        logger.info("[WORKER] Encontro %d eventos pendientes.", len(pendientes))

        for item in pendientes:
            audit_id = item["audit_id"]
            employee_id = item["employee_id"]

            try:
                await execute_etl_pipeline(audit_id=audit_id, employee_id=employee_id)
                logger.info("[WORKER] Audit ID %s procesado.", audit_id)
            except Exception as e:
                logger.error("[WORKER] Error procesando Audit ID %s: %s", audit_id, e)
                # Salvaguarda: Marcar status_flag = 3 para evitar bucle de reintentos infinitos
                try:
                    fail_conn = get_sqlserver_connection()
                    fail_cursor = fail_conn.cursor()
                    fail_cursor.execute(
                        "UPDATE dbo.ETL_AUDIT_LOG SET status_flag = 3, error_message = ?, updated_at = GETDATE() WHERE id = ? AND status_flag = 0",
                        (str(e), audit_id)
                    )
                    fail_conn.commit()
                    fail_cursor.close()
                    fail_conn.close()
                except Exception:
                    pass
