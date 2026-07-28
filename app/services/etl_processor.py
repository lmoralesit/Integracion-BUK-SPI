"""
Orquestador principal del flujo ETL: BUK → SQL Server → Oracle/SPI.

Clase ETLProcessor con método asíncrono que coordina la llamada a la API BUK, 
el almacenamiento en staging, la transformación de datos, la validación 
de pre-existencia, la inyección en Oracle SPI y la notificaciones por correo.
"""

import json
import logging
import traceback
from datetime import datetime
from typing import Any, Optional, Dict

import pyodbc
from pydantic import ValidationError

from app.config import settings
from app.routers.models import SPIEmployeePayload
from app.database.oracle import SPIDatabaseManager
from app.services.buk_client import BukAPIClient
from app.services.notifier import EmailNotifier
from app.utils.transformers import (
    formatear_rif,
    sanitizar_nombre,
    truncar_codigo_cargo,
    truncar_puesto,
    valor_neutro_contacto,
    limpiar_cedula,
    heredar_lugar_nacimiento,
)

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# Códigos de estado (Diccionario de Banderas)
# ──────────────────────────────────────────────
class StatusCode:
    """Banderas de estado para el procesamiento ETL."""
    PENDIENTE = 0
    EXITO = 1
    ADVERTENCIA = 2
    ERROR_INCONSISTENCIA = 3
    ERROR_SOCIETARIO = 4
    ERROR_CONEXION_ORACLE = 5
    DESCARTADO_DUPLICADO = 9


class ETLProcessor:
    """
    Orquestador del flujo ETL para nuevos ingresos de personal.
    """

    def __init__(
        self,
        sql_conn: pyodbc.Connection,
        buk_client: Optional[BukAPIClient] = None,
        notifier: Optional[EmailNotifier] = None,
    ):
        self.sql_conn = sql_conn
        self.buk_client = buk_client or BukAPIClient()
        self.notifier = notifier or EmailNotifier()

    def _actualizar_status_control(
        self,
        id_transaccion: int,
        status_code: int,
        mensaje_error: Optional[str] = None,
        ficha_asignada: Optional[str] = None,
    ):
        """Actualiza el estado de la transacción en ETL_BUK_Control_Ingresos."""
        try:
            cursor = self.sql_conn.cursor()
            cursor.execute(
                """
                UPDATE dbo.ETL_BUK_Control_Ingresos
                SET Status_Code = ?,
                    Mensaje_Error = ?,
                    Ficha_Asignada = COALESCE(?, Ficha_Asignada),
                    Fecha_Procesamiento = GETDATE()
                WHERE ID_Transaccion = ?
                """,
                status_code, mensaje_error, ficha_asignada, id_transaccion
            )
            self.sql_conn.commit()
            cursor.close()
        except pyodbc.Error as e:
            logger.error("[ERROR] Error actualizando status en SQL Server (ID %s): %s", id_transaccion, e)

    def _traducir_equivalencia(self, tipo_dato: str, valor_buk: str) -> str:
        """
        Tarea 3.4: Busca la equivalencia en dbo.ETL_BUK_Equivalencias
        usando las columnas reales (Tipo_Dato, Valor_BUK -> Codigo_SPI).
        """
        if not valor_buk:
            return ""
        try:
            cursor = self.sql_conn.cursor()
            cursor.execute(
                """
                SELECT Codigo_SPI 
                FROM dbo.ETL_BUK_Equivalencias 
                WHERE Tipo_Dato = ? AND Valor_BUK = ?
                """,
                tipo_dato, valor_buk
            )
            row = cursor.fetchone()
            cursor.close()
            if row and row[0]:
                return row[0]
        except Exception as e:
            logger.warning("[WARN] Error consultando equivalencia para %s (%s): %s", tipo_dato, valor_buk, e)

        logger.warning("[WARN] No se encontro equivalencia para %s: '%s' (Se usara el valor original)", tipo_dato, valor_buk)
        return valor_buk

    def obtener_siguiente_ficha(self) -> str:
        """
        Tarea 2.2: Reserva de forma atómica una nueva Ficha única correlativa (ej. F101)
        en SQL Server usando la tabla ETL_Correlativo_Ficha con bloqueos concurrrentes.
        """
        cursor = self.sql_conn.cursor()
        try:
            cursor.execute("""
                UPDATE dbo.ETL_Correlativo_Ficha WITH (UPDLOCK, ROWLOCK)
                SET Ultimo_Numero = Ultimo_Numero + 1
                OUTPUT INSERTED.Prefijo, INSERTED.Ultimo_Numero
                WHERE ID = 1
            """)
            row = cursor.fetchone()
            if not row:
                raise Exception("No se encontró registro semilla en ETL_Correlativo_Ficha (ID = 1).")
            prefijo = row[0]
            ultimo_numero = row[1]
            ficha = f"{prefijo}{ultimo_numero}"
            logger.info("[KEY] Ficha correlativa reservada atomicamente: %s", ficha)
            return ficha
        finally:
            cursor.close()

    async def procesar_nuevo_ingreso(self, employee_id: str | int, id_audit: Optional[int] = None) -> Dict[str, Any]:
        """
        Orquesta el flujo ETL completo para un nuevo ingreso BUK -> SPI.
        """
        id_transaccion: Optional[int] = None
        ficha_empleado: Optional[str] = None
        cedula_limpia: str = ""
        nombre_completo: str = ""

        try:
            # ════════════════════════════════════════
            # PASO 0: Extracción API BUK (Tarea 2.1)
            # ════════════════════════════════════════
            logger.info("[BUK-API] Obteniendo ficha completa del empleado %s desde API BUK...", employee_id)
            datos_buk = await self.buk_client.get_employee_detail(employee_id)

            if not datos_buk:
                raise ValueError(f"La API de BUK no devolvió datos para el empleado ID {employee_id}")

            attrs = datos_buk.get('custom_attributes', {}) or {}
            ficha_empleado = attrs.get('Ficha') or datos_buk.get('code_sheet')
            
            # Tarea 2.2: Reserva de Ficha atómica si no viene asignada desde BUK
            if not ficha_empleado:
                logger.info("   → Ficha BUK no asignada. Reservando correlativo atómico en SQL Server...")
                ficha_empleado = self.obtener_siguiente_ficha()

            cedula_cruda = datos_buk.get('document_number') or datos_buk.get('rut') or ""
            cedula_limpia = limpiar_cedula(cedula_cruda)
            
            nombres = sanitizar_nombre(datos_buk.get('first_name'))
            apellidos = sanitizar_nombre(datos_buk.get('surname'))
            nombre_completo = f"{nombres} {apellidos}".strip()

            # ════════════════════════════════════════
            # PASO 1: Guardar JSON crudo en SQL Staging (Tarea 2.3)
            # ════════════════════════════════════════
            logger.info("[STAGING] Paso 1: Almacenando JSON crudo en SQL Server (ETL_BUK_Control_Ingresos)...")
            json_crudo = json.dumps(datos_buk, ensure_ascii=False)
            cursor_sql = self.sql_conn.cursor()

            cursor_sql.execute(
                """
                INSERT INTO dbo.ETL_BUK_Control_Ingresos
                    (Payload_JSON, Cedula_Empleado, Ficha_Asignada, Status_Code)
                OUTPUT INSERTED.ID_Transaccion
                VALUES (?, ?, ?, ?)
                """,
                json_crudo,
                cedula_limpia,
                ficha_empleado,
                StatusCode.PENDIENTE,
            )
            row = cursor_sql.fetchone()
            id_transaccion = row[0]
            cursor_sql.close()
            self.sql_conn.commit()

            logger.info("   → Transacción registrada en Staging con ID: %s", id_transaccion)

            # ════════════════════════════════════════
            # PASO 2: Transformaciones & Sanitización (Módulo 3)
            # ════════════════════════════════════════
            logger.info("[TRANSFORM] Paso 2: Transformando y sanitizando atributos...")

            trabajo_actual = datos_buk.get('current_job', {}) or {}
            
            # Tarea 3.1: Sanitización RIF y Nombres
            rif_formateado = formatear_rif(attrs.get('tipo_rif'), attrs.get('RIF') or cedula_cruda)

            # Tarea 3.2: Cargos y Puestos (truncar a 36 chars y remover .0)
            codigo_cargo_crudo = attrs.get('codigo_cargo') or trabajo_actual.get('role', {}).get('id') or ""
            codigo_cargo = truncar_codigo_cargo(codigo_cargo_crudo)
            nombre_puesto = truncar_puesto(trabajo_actual.get('role', {}).get('name') or "EMPLEADO")

            # Tarea 3.3: Contacto neutro y Herencia lugar de nacimiento
            telefono = valor_neutro_contacto(datos_buk.get('phone') or datos_buk.get('cellphone'))
            email = valor_neutro_contacto(datos_buk.get('email'))

            direccion_res = datos_buk.get('address', '')
            ciudad_res = datos_buk.get('city', '')
            estado_res = datos_buk.get('state', '')
            lugar_nacimiento = heredar_lugar_nacimiento(datos_buk.get('country', 'VENEZUELA'), estado_res, ciudad_res)

            # Tarea 3.4: Equivalencias SQL Server (Localidad, Estado Civil, Sexo, Empresa)
            localidad_buk = str(trabajo_actual.get('location', {}).get('name') or attrs.get('Sede') or "").strip()
            localidad_spi = self._traducir_equivalencia('LOCALIDAD', localidad_buk)
            
            if not localidad_spi:
                msg_err = f"Error de Localidad: No se encontró mapeo para '{localidad_buk}'"
                logger.error("[ERROR] %s", msg_err)
                self._actualizar_status_control(id_transaccion, StatusCode.ERROR_INCONSISTENCIA, msg_err)
                # Tarea 5.2: Notificar a Capital Humano
                self.notifier.notificar_error_validacion(employee_id, cedula_limpia, nombre_completo, "Bandera 3: Error Localidad", msg_err)
                return {"id_transaccion": id_transaccion, "status_code": StatusCode.ERROR_INCONSISTENCIA, "mensaje": msg_err}

            estado_civil_spi = self._traducir_equivalencia('ESTADO_CIVIL', datos_buk.get('marital_status', 'Soltero'))
            sexo_spi = self._traducir_equivalencia('SEXO', datos_buk.get('gender', 'M'))
            if sexo_spi not in ("M", "F"):
                sexo_spi = "M"

            # Derivación de Empresa desde custom_attributes.codigo_empresa (Regla negocio)
            company_id_buk = str(attrs.get('codigo_empresa') or trabajo_actual.get('company_id') or "").strip()
            codigo_empresa_spi = self._traducir_equivalencia('EMPRESA', company_id_buk)

            if not codigo_empresa_spi:
                msg_err = f"Error Empresa: No se obtuvo un código de empresa válido de BUK ('{company_id_buk}')"
                logger.error("[ERROR] %s", msg_err)
                self._actualizar_status_control(id_transaccion, StatusCode.ERROR_SOCIETARIO, msg_err)
                # Tarea 5.2: Notificar a Capital Humano
                self.notifier.notificar_error_validacion(employee_id, cedula_limpia, nombre_completo, "Bandera 4: Error Empresa", msg_err)
                return {"id_transaccion": id_transaccion, "status_code": StatusCode.ERROR_SOCIETARIO, "mensaje": msg_err}

            # Cargas familiares (si existen)
            familiares_spi = []
            for familiar in datos_buk.get('family_members', []):
                parentesco_spi = self._traducir_equivalencia('PARENTESCO', familiar.get('relationship', ''))[:2] or "OT"
                familiares_spi.append({
                    "nombres_apellidos": sanitizar_nombre(familiar.get('name', ''))[:100],
                    "sexo": self._traducir_equivalencia('SEXO', familiar.get('gender', 'M')),
                    "fecha_nacimiento": str(familiar.get('birthday', '1900-01-01')) or "1900-01-01",
                    "tipo_parentesco": parentesco_spi,
                })

            datos_transformados = {
                "cedula": cedula_limpia,
                "primer_nombre": nombres,
                "segundo_nombre": "",
                "primer_apellido": apellidos,
                "segundo_apellido": "",
                "fecha_nacimiento": datos_buk.get('birthday', '1990-01-01'),
                "sexo": sexo_spi,
                "estado_civil": estado_civil_spi,
                "nacionalidad": datos_buk.get('nationality', 'VENEZOLANA'),
                "rif": rif_formateado,
                "telefono_celular": telefono,
                "correo_personal": email,
                "codigo_cargo": codigo_cargo,
                "nombre_cargo": nombre_puesto,
                "centro_costo": str(trabajo_actual.get('cost_center', 'CC-01')),
                "unidad_organizativa": str(trabajo_actual.get('area', {}).get('name') or "ADMINISTRACION")[:100],
                "codigo_empresa": codigo_empresa_spi,
                "fecha_inicio": trabajo_actual.get('start_date', datetime.now().strftime("%Y-%m-%d")),
                "ficha": ficha_empleado,
                "localidad": localidad_spi,
                "cargas_familiares": familiares_spi
            }

            # ════════════════════════════════════════
            # PASO 3: Capa de Carga y Transaccionalidad Oracle (Módulo 4)
            # ════════════════════════════════════════
            logger.info("[SPI] Paso 3: Validando pre-existencia e insertando en Oracle SPI...")

            payload_validado = SPIEmployeePayload(**datos_transformados)

            ora_manager = SPIDatabaseManager(
                dsn=f"{settings.ORACLE_HOST}:{settings.ORACLE_PORT}/{settings.ORACLE_SERVICE_NAME}",
                user=settings.ORACLE_USER,
                password=settings.ORACLE_PASSWORD,
                mock_mode=settings.ORACLE_MOCK,
            )

            # Tarea 4.1: Validación de Pre-existencia
            preexistencia = ora_manager.check_preexistencia(cedula_limpia)

            if preexistencia["contrato_abierto"]:
                msg_err = f"Pre-existencia laboral: La cédula {cedula_limpia} ya posee un contrato activo sin fecha de fin en SPI."
                logger.error("[ERROR] %s", msg_err)
                self._actualizar_status_control(id_transaccion, StatusCode.ERROR_SOCIETARIO, msg_err)
                # Tarea 5.2: Notificar error pre-existencia a Capital Humano
                self.notifier.notificar_error_validacion(employee_id, cedula_limpia, nombre_completo, "Bandera 4: Pre-existencia Abierta", msg_err)
                return {"id_transaccion": id_transaccion, "status_code": StatusCode.ERROR_SOCIETARIO, "mensaje": msg_err}

            # Tarea 4.2: Inyección InfoTypes SPI transaccional
            ora_manager.insert_employee_transactional(payload_validado)
            logger.info("[OK] Insercion en Oracle SPI comprometida (COMMIT) exitosamente.")

            # ════════════════════════════════════════
            # PASO 4: Retroalimentación a BUK (Tarea 4.3)
            # ════════════════════════════════════════
            logger.info("[PATCH] Paso 4: Commit en Oracle exitoso. Actualizando ficha en BUK via PATCH...")
            await self.buk_client.patch_employee_ficha(employee_id, ficha_empleado)

            # Actualizar status final éxito (Bandera 1)
            self._actualizar_status_control(id_transaccion, StatusCode.EXITO, ficha_asignada=ficha_empleado)

            # ════════════════════════════════════════
            # PASO 5: Notificación automatizada (Tarea 5.1)
            # ════════════════════════════════════════
            logger.info("[NOTIFY] Paso 5: Enviando notificacion de exito a Nomina...")
            self.notifier.notificar_exito(datos_transformados, localidad_buk)

            return {
                "id_transaccion": id_transaccion,
                "status_code": StatusCode.EXITO,
                "mensaje": f"Colaborador {nombre_completo} (Ficha {ficha_empleado}) procesado exitosamente.",
                "datos": datos_transformados
            }

        except ValidationError as ve:
            msg_err = f"ValidationError en payload SPI: {ve.json()}"
            logger.error("[ERROR] %s", msg_err)
            if id_transaccion:
                self._actualizar_status_control(id_transaccion, StatusCode.ERROR_INCONSISTENCIA, msg_err)
            self.notifier.notificar_error_validacion(employee_id, cedula_limpia, nombre_completo, "Bandera 3: Inconsistencia Datos", msg_err)
            return {"id_transaccion": id_transaccion, "status_code": StatusCode.ERROR_INCONSISTENCIA, "mensaje": msg_err}

        except Exception as e:
            traza = traceback.format_exc()
            logger.error("[ERROR] Error no controlado en ETLProcessor: %s\n%s", e, traza)
            if id_transaccion:
                self._actualizar_status_control(id_transaccion, StatusCode.ERROR_CONEXION_ORACLE, str(e))
            self.notifier.notificar_error_validacion(employee_id, cedula_limpia, nombre_completo, "Error Inesperado", str(e))
            return {"id_transaccion": id_transaccion, "status_code": StatusCode.ERROR_CONEXION_ORACLE, "mensaje": str(e)}


async def etl_onboarding_pipeline(audit_id: int, employee_id: str):
    """
    Función de entrada asíncrona para BackgroundTasks de FastAPI.
    Delega en execute_etl_pipeline de etl_engine.
    """
    from app.services.etl_engine import execute_etl_pipeline
    return await execute_etl_pipeline(audit_id=audit_id, employee_id=employee_id)

