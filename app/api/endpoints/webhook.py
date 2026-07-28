"""
Endpoint Receptor de Eventos en Tiempo Real (app.api.endpoints.webhook).
Aterriza los payloads JSON de BUK en Staging de manera parametrizada y segura.
"""
import json
import logging
from fastapi import APIRouter, Depends, status, HTTPException
from pydantic import BaseModel, Field
from app.core.security import verify_buk_signature
from app.database.sql_server import get_sqlserver_connection

logger = logging.getLogger("ETL_BUK_SPI")
router = APIRouter()

class BukWebhookData(BaseModel):
    employee_id: int | str = Field(..., description="ID del colaborador en BUK")
    event_type: str = Field(default="employee_create", description="Tipo de evento disparado")

class BukWebhookPayload(BaseModel):
    data: BukWebhookData

    class Config:
        extra = "allow"  # Permite recibir metadata adicional sin romper la validación

@router.post(
    "/buk/employee",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(verify_buk_signature)],
    summary="Receptor Asíncrono de Eventos BUK"
)
async def receive_buk_webhook(payload: BukWebhookPayload):
    """
    1. Valida criptográficamente el tráfico entrante (Mandamiento #4).
    2. Persiste el evento en SQL Server Staging (ETL_AUDIT_LOG) usando SQL parametrizada (Mandamiento #1).
    3. Responde HTTP 202 Accepted al instante para liberar la cola de BUK.
    """
    conn = None
    try:
        emp_id = str(payload.data.employee_id)
        ev_type = str(payload.data.event_type)
        raw_json = json.dumps(payload.dict(), ensure_ascii=False)

        conn = get_sqlserver_connection()
        cursor = conn.cursor()
        
        # Mandamiento #1: Consulta 100% parametrizada. Cero concatenaciones f-string en DML.
        query_staging = """
            INSERT INTO dbo.ETL_AUDIT_LOG (employee_id, event_type, status_flag, raw_payload, created_at, updated_at)
            OUTPUT INSERTED.id
            VALUES (?, ?, 0, ?, GETDATE(), GETDATE());
        """
        cursor.execute(query_staging, (emp_id, ev_type, raw_json))
        row = cursor.fetchone()
        audit_id = row[0] if row else 0
        
        conn.commit() # Mandamiento #3: Commit transaccional explícito
        logger.info("[WEBHOOK RECIBIDO] Evento '%s' para Empleado ID: %s encolado en Staging (ID Log: %s).", ev_type, emp_id, audit_id)
        
        return {
            "status": "Accepted",
            "audit_id": audit_id,
            "message": "Evento persistido en ODS exitosamente. El Worker procesará en segundo plano."
        }
    except Exception as exc:
        if conn:
            conn.rollback()
        logger.error("[WEBHOOK FALLO] Error al registrar evento en Staging: %s", str(exc))
        raise HTTPException(status_code=500, detail="Fallo de persistencia transaccional en Staging.")
    finally:
        if conn:
            conn.close()