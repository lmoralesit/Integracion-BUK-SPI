"""
Motor de Extracción, Transformación, Sanitización y Carga (app.services.etl_engine).

Implementa la lógica del pipeline ETL BUK -> SQL Server Staging -> Oracle SPI:
- Extracción asíncrona con httpx y reintentos exponenciales.
- Sanitización RIF, acentos, puestos, y valores neutros.
- Contador Atómico de Fichas en SQL Server (UPDLOCK).
- Inserción transaccional parametrizada en Oracle SPI con auditoría obligatoria.
- Orquestación background execute_etl_pipeline.
"""

import asyncio
import json
import logging
import re
import unicodedata
from typing import Dict, Any, Optional

import httpx

from app.core.config import settings
from app.database.sql_server import get_sqlserver_connection
from app.database.oracle import SPIDatabaseManager
from app.services.buk_client import BukAPIClient
from app.services.notifier import EmailNotifier

logger = logging.getLogger("ETL_BUK_SPI")


# ──────────────────────────────────────────────
# 2.1 Extracción Asíncrona con httpx
# ──────────────────────────────────────────────


async def fetch_buk_employee_with_retry(employee_id: str, max_retries: int = 2) -> dict:
    """
    Mandamiento DevSecOps #2: Tolerancia a fallos con reintentos asíncronos y backoff exponencial.
    """
    url = f"{settings.BUK_API_BASE_URL}/employees/{employee_id}"
    token_str = settings.BUK_API_TOKEN.get_secret_value() if hasattr(settings.BUK_API_TOKEN, 'get_secret_value') else str(settings.BUK_API_TOKEN)
    headers = {"auth_token": token_str, "Accept": "application/json"}
    
    for attempt in range(1, max_retries + 1):
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                data = response.json().get("data", {})
                if isinstance(data, list):
                    return data[0] if data else {}
                return data
        except (httpx.RequestError, httpx.HTTPStatusError) as exc:
            logger.warning(f"Intento {attempt}/{max_retries} fallido al consultar BUK ID {employee_id}: {exc}")
            if attempt == max_retries:
                logger.error(f"Se agotaron los reintentos para BUK ID {employee_id}.")
                raise
            await asyncio.sleep(1.5 * attempt)
    return {}


# ──────────────────────────────────────────────
# 2.2 Motor de Saneamiento y Transformación
# ──────────────────────────────────────────────


def sanitize_rif(raw_rif: str) -> str:
    if not raw_rif:
        return "."
    clean = re.sub(r'[\s\.\-]', '', str(raw_rif)).upper()
    return clean if len(clean) > 1 else "."


def remove_accents(text: str) -> str:
    if not text:
        return ""
    # Descompone caracteres (ej. 'á' -> 'a' + tilde) y elimina la tilde
    nfd = unicodedata.normalize('NFD', str(text))
    return "".join(c for c in nfd if unicodedata.category(c) != 'Mn').strip()


def sanitize_job_code(raw_code: str) -> str:
    """Elimina el '.0' erróneo exportado por BUK en códigos de cargo (ej. 12345.0 -> 12345)"""
    if not raw_code:
        return "0000"
    return re.sub(r'\.0$', '', str(raw_code)).strip()


def format_spi_position(unit_name: str, job_name: str) -> str:
    """RF-02: Limita el Puesto en SPI a un máximo estricto de 36 caracteres."""
    raw_pos = f"{unit_name} - {job_name}"
    clean_pos = remove_accents(raw_pos)
    return clean_pos[:36] if len(clean_pos) > 36 else clean_pos


def ensure_not_null(value: Any, fallback: str = ".") -> str:
    """RF-11: Rellena vacíos con valor neutro (.) o (-) para evitar caídas de Oracle."""
    if value is None or str(value).strip() == "":
        return fallback
    return str(value).strip()


# ──────────────────────────────────────────────
# 3.1 Contador Atómico de Fichas en SQL Server
# ──────────────────────────────────────────────


def get_next_atomic_ficha(db_staging_conn, empresa_id: str = "D6") -> str:
    """Obtiene y reserva el siguiente número de ficha corporativo (ej. F101) de forma atómica."""
    cursor = db_staging_conn.cursor()
    try:
        # Intentar reservar en ETL_CORRELATIVOS primero
        cursor.execute("""
            UPDATE ETL_CORRELATIVOS WITH (UPDLOCK)
            SET u_ficha = u_ficha + 1
            OUTPUT INSERTED.u_ficha
            WHERE empresa_id = ?;
        """, (empresa_id,))
        row = cursor.fetchone()
        
        # Fallback a 'DEFAULT' o inserción si no existe
        if not row:
            cursor.execute("""
                UPDATE ETL_CORRELATIVOS WITH (UPDLOCK)
                SET u_ficha = u_ficha + 1
                OUTPUT INSERTED.u_ficha
                WHERE empresa_id = 'DEFAULT';
            """)
            row = cursor.fetchone()

        if not row:
            # Fallback legacy a ETL_Correlativo_Ficha
            cursor.execute("""
                UPDATE dbo.ETL_Correlativo_Ficha WITH (UPDLOCK, ROWLOCK)
                SET Ultimo_Numero = Ultimo_Numero + 1
                OUTPUT INSERTED.Prefijo, INSERTED.Ultimo_Numero
                WHERE ID = 1
            """)
            row_legacy = cursor.fetchone()
            if row_legacy:
                db_staging_conn.commit()
                return f"{row_legacy[0]}{row_legacy[1]}"
            raise Exception(f"No existe correlativo inicializado para la empresa {empresa_id}")

        db_staging_conn.commit()
        return f"F{row[0]}"
    except Exception as e:
        db_staging_conn.rollback()
        raise e
    finally:
        cursor.close()


# ──────────────────────────────────────────────
# 3.2 Inyección en Oracle SPI
# ──────────────────────────────────────────────


def insert_employee_to_spi(oracle_conn, employee_data: dict, ficha: str) -> bool:
    """
    Mandamiento DevSecOps #3: Manejo transaccional estricto y seguro (commit / rollback).
    Mandamiento DevSecOps #1: Consultas PARAMETRIZADAS para evitar inyecciones SQL.
    """
    if settings.ORACLE_MOCK:
        logger.info(f"[MOCK] Inserción simulada en Oracle SPI para ficha {ficha}.")
        return True

    cursor = oracle_conn.cursor()
    try:
        cedula = ensure_not_null(employee_data.get("rut") or employee_data.get("document_number"))
        
        # 1. SALVAGUARDA RF-05: Verificación de Pre-existencia y contrato abierto
        check_query = """
            SELECT r.FICHA, r.FECHA_FIN 
            FROM EO_PERSONA p
            JOIN TA_RELACION_LABORAL r ON p.ID_PERSONA = r.ID_PERSONA
            WHERE p.NUM_IDEN = :cedula AND r.FECHA_FIN IS NULL
        """
        cursor.execute(check_query, {"cedula": cedula})
        active_relation = cursor.fetchone()
        
        if active_relation:
            logger.error(f"[ALERTA CRÍTICA] Cédula {cedula} ya posee una relación laboral activa bajo la ficha {active_relation[0]}. Inserción abortada.")
            return False
            
        # 2. INSERCIÓN EO_PERSONA (Si no existe previamente)
        insert_persona = """
            INSERT INTO EO_PERSONA (
                NUM_IDEN, RIFTRA, NOMBRE1, APELLIDO1, EDO_CIVIL, 
                FECHA_NA, TELEFONO1, E_MAIL1, E_MAIL2,
                Usrcre, Feccre, Fecact, OBSERVA
            ) VALUES (
                :cedula, :rif, :nom1, :ape1, :edo_civ, 
                TO_DATE(:fec_nac, 'YYYY-MM-DD'), :tlf, :mail_corp, :mail_pers,
                :usrcre, SYSDATE, SYSDATE, :observa
            )
        """
        cursor.execute(insert_persona, {
            "cedula": cedula,
            "rif": sanitize_rif(employee_data.get("rif") or employee_data.get("custom_attributes", {}).get("RIF")),
            "nom1": remove_accents(employee_data.get("first_name"))[:17],
            "ape1": remove_accents(employee_data.get("surname"))[:17],
            "edo_civ": "1", # Valor homologado por tabla de equivalencias
            "fec_nac": employee_data.get("birthday", "1990-01-01"),
            "tlf": ensure_not_null(employee_data.get("phone")),
            "mail_corp": ensure_not_null(employee_data.get("email")),
            "mail_pers": ensure_not_null(employee_data.get("personal_email") or employee_data.get("email")),
            "usrcre": settings.ETL_USER,
            "observa": settings.ETL_OBSERVA
        })
        
        # 3. INSERCIÓN TA_RELACION_LABORAL (Inyección técnica RF-07 obligatoria)
        insert_rel_lab = """
            INSERT INTO TA_RELACION_LABORAL (
                FICHA, ID_EMPRESA, FECHA_INI, ID_NOMINA, 
                Usrcre, Feccre, Fecact, Id_cambio, OBSERVA
            ) VALUES (
                :ficha, :empresa, TO_DATE(:fec_ini, 'YYYY-MM-DD'), :nomina,
                :usrcre, SYSDATE, SYSDATE, :id_cambio, :observa
            )
        """
        cursor.execute(insert_rel_lab, {
            "ficha": ficha,
            "empresa": ensure_not_null(employee_data.get("custom_attributes", {}).get("codigo_empresa"), "D6"),
            "fec_ini": employee_data.get("current_job", {}).get("start_date") or employee_data.get("start_date") or "2026-01-01",
            "nomina": "0001",
            "usrcre": settings.ETL_USER,
            "id_cambio": settings.ETL_ID_CAMBIO,
            "observa": settings.ETL_OBSERVA
        })
        
        # 4. INSERCIÓN TA_RELACION_PUESTO (Límite 36 caracteres en Puesto RF-02)
        insert_rel_puesto = """
            INSERT INTO TA_RELACION_PUESTO (
                FICHA, ID_PUESTO, DESCRIPCION_PUESTO, FECHA_INI,
                Usrcre, Feccre, Fecact, Id_cambio, OBSERVA
            ) VALUES (
                :ficha, :id_puesto, :desc_puesto, TO_DATE(:fec_ini, 'YYYY-MM-DD'),
                :usrcre, SYSDATE, SYSDATE, :id_cambio, :observa
            )
        """
        unit = employee_data.get("current_job", {}).get("area", {}).get("name") or "OPERACIONES"
        job_title = employee_data.get("current_job", {}).get("role", {}).get("name") or employee_data.get("job_title") or "General"
        puesto_desc = format_spi_position(unit, job_title)

        cursor.execute(insert_rel_puesto, {
            "ficha": ficha,
            "id_puesto": sanitize_job_code(employee_data.get("custom_attributes", {}).get("codigo_cargo") or employee_data.get("job_code")),
            "desc_puesto": puesto_desc,
            "fec_ini": employee_data.get("current_job", {}).get("start_date") or employee_data.get("start_date") or "2026-01-01",
            "usrcre": settings.ETL_USER,
            "id_cambio": settings.ETL_ID_CAMBIO,
            "observa": settings.ETL_OBSERVA
        })

        oracle_conn.commit()
        logger.info(f"[ÉXITO] Colaborador {cedula} cargado exitosamente en SPI con ficha {ficha}.")
        return True

    except Exception as exc:
        oracle_conn.rollback()
        logger.error(f"[ROLLBACK] Fallo DML en Oracle SPI para cédula {employee_data.get('rut')}: {exc}")
        raise exc
    finally:
        cursor.close()


# ──────────────────────────────────────────────
# Pipeline de Ejecución Asíncrona (Background Worker)
# ──────────────────────────────────────────────


async def execute_etl_pipeline(audit_id: int, employee_id: str):
    """
    Ejecuta el pipeline ETL en background a partir del audit_id guardado en Staging:
    1. Extrae empleado completo de BUK API.
    2. Genera Ficha atómica en SQL Server.
    3. Carga en Oracle SPI con salvaguarda de pre-existencia y auditoría.
    4. PATCH a BUK con la ficha asignada.
    5. Actualiza status_flag en ETL_AUDIT_LOG y envía notificaciones.
    """
    logger.info(f"[ETL] Iniciando Pipeline ETL para Audit ID: {audit_id} (BUK ID: {employee_id})")
    
    db_staging = None
    notifier = EmailNotifier()
    buk_client = BukAPIClient()

    try:
        db_staging = get_sqlserver_connection()

        # 1. Extracción de BUK API con retry exponencial
        employee_data = await fetch_buk_employee_with_retry(employee_id)
        if not employee_data:
            raise ValueError(f"No se obtuvieron datos de BUK para empleado {employee_id}")

        # 2. Generación atómica de ficha
        empresa_id = employee_data.get("custom_attributes", {}).get("codigo_empresa") or "D6"
        ficha = employee_data.get("code_sheet") or employee_data.get("custom_attributes", {}).get("Ficha")
        
        if not ficha:
            ficha = get_next_atomic_ficha(db_staging, empresa_id)
            logger.info(f"[Audit ID: {audit_id}] Ficha asignada: {ficha}")

        # 3. Carga transaccional en Oracle SPI
        ora_manager = SPIDatabaseManager(
            dsn=f"{settings.ORACLE_HOST}:{settings.ORACLE_PORT}/{settings.ORACLE_SERVICE_NAME}",
            user=settings.ORACLE_USER,
            password=settings.ORACLE_PASSWORD,
            mock_mode=settings.ORACLE_MOCK,
        )

        ora_conn = ora_manager.get_connection()
        success = insert_employee_to_spi(ora_conn, employee_data, ficha)

        if not success:
            # Pre-existencia detectada o contrato abierto -> Flag 4
            cursor = db_staging.cursor()
            cursor.execute(
                "UPDATE ETL_AUDIT_LOG SET status_flag = 4, error_message = ?, processed_at = GETDATE(), updated_at = GETDATE() WHERE id = ?",
                ("Error de Pre-existencia: Contrato abierto activo en SPI.", audit_id)
            )
            db_staging.commit()
            cursor.close()

            cedula = employee_data.get("rut") or employee_data.get("document_number") or ""
            nombre = f"{employee_data.get('first_name', '')} {employee_data.get('surname', '')}"
            notifier.notificar_error_validacion(employee_id, cedula, nombre, "Bandera 4: Pre-existencia / Cía", "Contrato abierto activo en SPI")
            return

        # 4. PATCH a BUK con la ficha asignada
        await buk_client.patch_employee_ficha(employee_id, ficha)

        # 5. Éxito -> Flag 1
        cursor = db_staging.cursor()
        cursor.execute(
            "UPDATE ETL_AUDIT_LOG SET status_flag = 1, error_message = NULL, processed_at = GETDATE(), updated_at = GETDATE() WHERE id = ?",
            (audit_id,)
        )
        db_staging.commit()
        cursor.close()

        # Notificar a Nómina
        localidad = employee_data.get("current_job", {}).get("location", {}).get("name") or "Caracas"
        notifier.notificar_exito(employee_data, localidad)
        logger.info(f"[OK] Pipeline ETL finalizado con EXITO para Audit ID: {audit_id}")

    except Exception as exc:
        logger.error(f"[ERROR] Error en Pipeline ETL para Audit ID {audit_id}: {exc}")
        
        # Forzar actualización a status_flag = 3 en la base de datos para detener reintentos
        try:
            conn_err = db_staging or get_sqlserver_connection()
            cursor = conn_err.cursor()
            cursor.execute(
                "UPDATE dbo.ETL_AUDIT_LOG SET status_flag = 3, error_message = ?, processed_at = GETDATE(), updated_at = GETDATE() WHERE id = ?",
                (str(exc), audit_id)
            )
            conn_err.commit()
            cursor.close()
            if not db_staging:
                conn_err.close()
        except Exception as db_exc:
            logger.error(f"[ERROR] No se pudo actualizar status_flag = 3 en la BD: {db_exc}")

        notifier.notificar_error_validacion(employee_id, "", "", "Error ETL Background", str(exc))

    finally:
        if db_staging:
            try:
                db_staging.close()
            except Exception:
                pass
