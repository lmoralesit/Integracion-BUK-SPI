"""
Router de la Interfaz Visual Administrativa (app.api.endpoints.admin).
Provee el Panel de Monitoreo embebido (/admin/dashboard) y la capacidad de relanzar jobs.
"""

import logging
from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from app.core.db import get_staging_db

logger = logging.getLogger("ETL_BUK_SPI")
router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/dashboard", response_class=HTMLResponse)
async def admin_dashboard(request: Request, db = Depends(get_staging_db)):
    """
    Renderiza la vista principal de monitoreo con las últimas transacciones ETL.
    Sanitiza y aplana las variables, utilizando argumentos de palabra clave en TemplateResponse
    para compatibilidad estricta con Starlette 0.28+ / FastAPI moderno.
    """
    cursor = db.cursor()
    cursor.execute("""
        SELECT TOP 50 id, employee_id, event_type, status_flag, error_message, created_at
        FROM dbo.ETL_AUDIT_LOG
        ORDER BY created_at DESC;
    """)
    rows = cursor.fetchall()
    cursor.close()
    
    # Mapeo plano en Backend para evitar pasar estructuras complejas a Jinja2
    status_map_interno = {
        0: ("Pendiente", "bg-yellow-500"),
        1: ("Procesado OK", "bg-green-600"),
        2: ("Reintentando", "bg-blue-500"),
        3: ("Err. Localidad/Datos", "bg-orange-600"),
        4: ("Err. Pre-existencia / Cía", "bg-red-600")
    }
    
    logs_procesados = []
    for r in rows:
        st_label, st_color = status_map_interno.get(r[3], ("Desconocido", "bg-gray-500"))
        logs_procesados.append({
            "id": r[0],
            "employee_id": r[1],
            "event_type": r[2],
            "status_flag": r[3],
            "status_label": st_label,
            "status_color": st_color,
            "error_message": r[4] if r[4] else "N/A",
            "created_at": r[5].strftime('%Y-%m-%d %H:%M:%S') if r[5] else ""
        })
    
    # Mandamiento DevSecOps: Uso explícito de argumentos por palabra clave (keyword arguments)
    # para evitar colisiones de firma posicional entre versiones de Starlette/FastAPI.
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "request": request,
            "logs": logs_procesados
        }
    )


@router.post("/retry/{audit_id}")
async def retry_failed_job(audit_id: int, db = Depends(get_staging_db)):
    """
    Permite relanzar un job fallido desde la interfaz visual tras corrección manual en BUK.
    Mandamiento #3: Idempotencia y control transaccional explícito.
    """
    cursor = db.cursor()
    cursor.execute("UPDATE dbo.ETL_AUDIT_LOG SET status_flag = 0, error_message = NULL WHERE id = ?", (audit_id,))
    db.commit()
    cursor.close()
    logger.info(f"Relanzado manualmente el job de auditoría ID: {audit_id}")
    return RedirectResponse(url="/admin/dashboard", status_code=status.HTTP_303_SEE_OTHER)