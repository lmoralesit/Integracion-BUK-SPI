import hmac
import hashlib
import logging
from fastapi import Header, HTTPException, status, Request
from app.core.config import settings

logger = logging.getLogger("ETL_BUK_SPI")

async def verify_buk_signature(request: Request, x_buk_signature: str = Header(None)) -> bool:
    """
    Mandamiento #4 & OWASP Top 10: Validación criptográfica en tiempo constante (Anti-Timing Attack).
    Verifica que el payload entrante esté firmado por el secreto BUK_WEBHOOK_SECRET[cite: 1, 4].
    """
    if not x_buk_signature:
        logger.warning("Alerta de Seguridad: Intento de acceso a Webhook sin cabecera X-Buk-Signature.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Cabecera criptográfica X-Buk-Signature ausente."
        )
    
    # Leer body crudo sin consumirlo permanentemente para el resto del pipeline
    payload_bytes = await request.body()
    
    expected_signature = hmac.new(
        key=settings.BUK_WEBHOOK_SECRET.encode("utf-8"),
        msg=payload_bytes,
        digestmod=hashlib.sha256
    ).hexdigest()
    
    if not hmac.compare_digest(x_buk_signature, expected_signature):
        # Mandamiento #5: No logueamos el secreto ni el payload sensible, solo el evento hostil
        logger.error("Alerta de Seguridad: Firma HMAC rechazada. Posible interceptación o secreto incorrecto.")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Firma criptográfica no autorizada."
        )
    
    return True