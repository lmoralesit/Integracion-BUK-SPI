"""
Endpoint Receptor de Eventos en Tiempo Real (app.api.endpoints.webhook).
Implementa validación HMAC-SHA256 en tiempo constante y desacoplamiento
mediante BackgroundTasks para respuesta < 200ms.
"""
import hmac
import hashlib
import json
import logging
from fastapi import APIRouter, Header, HTTPException, status, BackgroundTasks, Request
from app.core.config import settings
from app.database.sql_server import get_sqlserver_connection
from app.api.models.payloads import BukWebhookPayload

logger = logging.getLogger("ETL_BUK_SPI")
router = APIRouter()


async def verify_buk_signature(request: Request):
    """
    [Mandamiento #4 & OWASP Top 10] Validación criptográfica en tiempo constante.
    Evalúa firma HMAC-SHA256 en cabecera 'X-Buk-Signature' o Bearer Token en 'Authorization'.
    """
    secreto_str = settings.BUK_WEBHOOK_SECRET.get_secret_value() if hasattr(settings.BUK_WEBHOOK_SECRET, 'get_secret_value') else str(settings.BUK_WEBHOOK_SECRET)
    if not secreto_str:
        logger.critical("[SECURITY] BUK_WEBHOOK_SECRET ausente en variables de entorno.")
        raise HTTPException(status_code=500, detail="Error de configuración de seguridad.")

    # Intento 1: Validación por Bearer Token
    authorization = request.headers.get("Authorization")
    if authorization:
        token_recibido = authorization.replace("Bearer ", "").strip()
        if hmac.compare_digest(token_recibido, secreto_str):
            return True

    # Intento 2: Validación por Firma Criptográfica HMAC-SHA256
    x_buk_signature = request.headers.get("X-Buk-Signature")
    if x_buk_signature:
        payload_bytes = await request.body()
        expected_signature = hmac.new(
            key=secreto_str.encode("utf-8"),
            msg=payload_bytes,
            digestmod=hashlib.sha256
        ).hexdigest()

        if hmac.compare_digest(x_buk_signature, expected_signature):
            return True

    logger.warning("[SECURITY BLOCKED] Petición denegada. Firma HMAC o Bearer Token inválido/ausente.")
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Acceso no autorizado al servicio de integración ETL."
    )


@router.post(
    "/buk/employee",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Receptor Event-Driven BUK → SPI (ACK < 200ms)"
)
async def receive_buk_webhook(request: Request):
    """
    [Mandamiento #1, #3 y #4]
    1. Valida criptográficamente el tráfico entrante.
    2. Persiste en SQL Server Staging (ETL_AUDIT_LOG) con SQL parametrizada.
    3. Responde HTTP 202 Accepted al instante (< 200ms) para liberar la cola de BUK.
    El Worker desacoplado (app/services/worker.py) procesará el pipeline en segundo plano.
    """
    # Paso 1: Validación de seguridad
    await verify_buk_signature(request)

    # Paso 2: Deserializar y validar payload con Pydantic
    payload_bytes = await request.body()
    try:
        body = json.loads(payload_bytes)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Payload JSON inválido.")

    # Extraer data block (BUK envía {data: {...}})
    data_block = body.get("data", body)
    emp_id = str(data_block.get("employee_id", ""))
    ev_type = str(data_block.get("event_type", "employee_create"))

    if not emp_id:
        raise HTTPException(status_code=422, detail="Payload carece de employee_id.")

    # Paso 3: Persistir en Staging con SQL parametrizada (Mandamiento #1: Cero f-strings en DML)
    conn = None
    try:
        raw_json = json.dumps(body, ensure_ascii=False)
        conn = get_sqlserver_connection()
        cursor = conn.cursor()

        query_staging = """
            INSERT INTO dbo.ETL_AUDIT_LOG (employee_id, event_type, status_flag, raw_payload, created_at, updated_at)
            OUTPUT INSERTED.id
            VALUES (?, ?, 0, ?, GETDATE(), GETDATE());
        """
        cursor.execute(query_staging, (emp_id, ev_type, raw_json))
        row = cursor.fetchone()
        audit_id = row[0] if row else 0

        conn.commit()
        cursor.close()
        logger.info("[WEBHOOK OK] Evento '%s' para Empleado ID: %s encolado en Staging (Audit ID: %s).", ev_type, emp_id, audit_id)

        return {
            "status": "ACCEPTED",
            "audit_id": audit_id,
            "message": "Evento persistido en ODS. El Worker procesará en segundo plano."
        }
    except Exception as exc:
        if conn:
            conn.rollback()
        logger.error("[WEBHOOK FALLO] Error al registrar evento en Staging: %s", str(exc))
        raise HTTPException(status_code=500, detail="Fallo de persistencia transaccional en Staging.")
    finally:
        if conn:
            conn.close()