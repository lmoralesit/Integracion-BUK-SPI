"""
Inyección de Dependencias para Ciberseguridad (app.core.security).
Valida las firmas HMAC-SHA256 o Bearer Tokens provenientes del Webhook de BUK.
"""
import hmac
import hashlib
import logging
from fastapi import Header, HTTPException, status, Request
from app.core.config import settings

logger = logging.getLogger("ETL_BUK_SPI")

async def verify_buk_signature(
    request: Request,
    x_buk_signature: str = Header(None, alias="X-Buk-Signature"),
    authorization: str = Header(None, alias="Authorization")
) -> bool:
    """
    Mandamiento DevSecOps #4: Asume que todo tráfico entrante es hostil.
    Evalúa firma HMAC-SHA256 en cabecera 'X-Buk-Signature' o el Bearer Token configurado en el panel web.
    """
    secreto_str = settings.BUK_WEBHOOK_SECRET.get_secret_value()
    if not secreto_str:
        logger.error("[SECURITY] Secreto de Webhook no configurado en el backend.")
        raise HTTPException(status_code=500, detail="Error interno de seguridad en el servidor.")

    # 1. Intento de validación por Token Bearer (Configurado en el panel web de BUK)
    if authorization:
        token_recibido = authorization.replace("Bearer ", "").strip()
        if hmac.compare_digest(token_recibido, secreto_str):
            return True

    # 2. Intento de validación por Firma Criptográfica HMAC SHA-256
    if x_buk_signature:
        payload_bytes = await request.body()
        expected_signature = hmac.new(
            key=secreto_str.encode("utf-8"),
            msg=payload_bytes,
            digestmod=hashlib.sha256
        ).hexdigest()
        
        if hmac.compare_digest(x_buk_signature, expected_signature):
            return True

    # Mandamiento #5: Loguear intrusión sin revelar PII ni imprimir los secretos en claro
    logger.warning("[SECURITY BLOCKED] Petición denegada al Webhook. Firma HMAC o Bearer Token inválido/ausente.")
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Acceso no autorizado al servicio de integración ETL."
    )
