"""
Módulo de conexión a Oracle Database – Capa Destino (SPI / Infocent).

Utiliza oracledb (python-oracledb) para conexiones directas en modo thin
(sin Oracle Client). Incluye manejo de excepciones y logging.
"""

import logging
from typing import Dict, Any, Tuple
from unittest.mock import Mock, MagicMock
from pydantic import SecretStr

import oracledb

from app.config import settings
from app.api.models.payloads import SPIEmployeePayload

logger = logging.getLogger(__name__)


class SPIDatabaseManager:
    def __init__(self, dsn: str, user: str, password: str | SecretStr, mock_mode: bool = False):
        self.dsn = dsn
        self.user = user
        self.password = password
        self.mock_mode = mock_mode

    def get_connection(self):
        if self.mock_mode or settings.ORACLE_MOCK:
            logger.info("[MOCK] Usando conexion simulada Mock para Oracle SPI")
            mock_conn = MagicMock()
            mock_conn.__enter__.return_value = mock_conn
            mock_cursor = MagicMock()
            mock_cursor.fetchone.return_value = (0,)
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
            return mock_conn

        pwd = self.password.get_secret_value() if hasattr(self.password, 'get_secret_value') else self.password
        return oracledb.connect(
            user=self.user, 
            password=pwd, 
            dsn=self.dsn
        )

    def check_preexistencia(self, cedula: str) -> Dict[str, bool]:
        """
        Tarea 4.1 (Validación de Pre-existencia):
        Consultar EO_PERSONA por cédula. Si existe, validar en TA_RELACION_LABORAL
        que no tenga un contrato abierto sin fecha de fin (FECFIN IS NULL).
        """
        if self.mock_mode or settings.ORACLE_MOCK:
            logger.info("[MOCK] Busqueda pre-existencia cedula: %s (Simulado: NO existe)", cedula)
            return {"persona_existe": False, "contrato_abierto": False}

        persona_existe = False
        contrato_abierto = False

        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                # 1. Consultar en EO_PERSONA
                cursor.execute("SELECT COUNT(1) FROM EO_PERSONA WHERE CEDULA = :cedula", {"cedula": cedula})
                row = cursor.fetchone()
                if row and row[0] > 0:
                    persona_existe = True

                # 2. Si existe, consultar contratos abiertos en TA_RELACION_LABORAL
                if persona_existe:
                    cursor.execute(
                        """
                        SELECT COUNT(1) 
                        FROM TA_RELACION_LABORAL 
                        WHERE CEDULA = :cedula 
                          AND (FECFIN IS NULL OR FECFIN > SYSDATE)
                        """,
                        {"cedula": cedula}
                    )
                    row_laboral = cursor.fetchone()
                    if row_laboral and row_laboral[0] > 0:
                        contrato_abierto = True

        logger.info(
            "[SPI] Validacion Pre-existencia cedula %s -> Persona existe: %s, Contrato abierto: %s",
            cedula, persona_existe, contrato_abierto
        )
        return {"persona_existe": persona_existe, "contrato_abierto": contrato_abierto}

    def insert_employee_transactional(self, employee: SPIEmployeePayload):
        """
        Tarea 4.2 (Inyección InfoTypes SPI):
        Ejecuta sentencias SQL parametrizadas nativas en bloque transaccional (try...except...rollback())
        inyectando mandatoriamente los campos de auditoría:
            Usrcre = settings.ETL_USER ("ETL")
            Feccre / Fecact = Fecha Sistema (SYSDATE)
            Id_cambio = settings.ETL_ID_CAMBIO ("10001")
            OBSERVA = settings.ETL_OBSERVA ("CREADO POR ETL")
        """
        if self.mock_mode or settings.ORACLE_MOCK:
            logger.info("[MOCK] Insercion transaccional simulada en SPI para cedula: %s", employee.cedula)
            return

        with self.get_connection() as conn:
            try:
                with conn.cursor() as cursor:
                    # 1. Inserción en EO_PERSONA (si no existe previa)
                    sql_persona = """
                        INSERT INTO EO_PERSONA (
                            CEDULA, PRIMER_NOMBRE, SEGUNDO_NOMBRE, PRIMER_APELLIDO, 
                            SEGUNDO_APELLIDO, SEXO, FECHA_NACIMIENTO, RIF, NACIONALIDAD,
                            ESTADO_CIVIL, USRCRE, FECCRE, FECACT, ID_CAMBIO, OBSERVA
                        ) VALUES (
                            :cedula, :primer_nombre, :segundo_nombre, :primer_apellido,
                            :segundo_apellido, :sexo, TO_DATE(:fecha_nacimiento, 'YYYY-MM-DD'), 
                            :rif, :nacionalidad, :estado_civil, :usrcre, SYSDATE, SYSDATE, :id_cambio, :observa
                        )
                    """
                    cursor.execute(sql_persona, {
                        "cedula": employee.cedula,
                        "primer_nombre": employee.primer_nombre,
                        "segundo_nombre": employee.segundo_nombre[:50] if employee.segundo_nombre else "",
                        "primer_apellido": employee.primer_apellido,
                        "segundo_apellido": employee.segundo_apellido[:50] if employee.segundo_apellido else "",
                        "sexo": employee.sexo,
                        "fecha_nacimiento": str(employee.fecha_nacimiento),
                        "rif": employee.rif,
                        "nacionalidad": employee.nacionalidad,
                        "estado_civil": employee.estado_civil,
                        "usrcre": settings.ETL_USER,
                        "id_cambio": settings.ETL_ID_CAMBIO,
                        "observa": settings.ETL_OBSERVA,
                    })

                    # 2. Inserción en TA_RELACION_LABORAL
                    sql_laboral = """
                        INSERT INTO TA_RELACION_LABORAL (
                            CEDULA, CODEMPRESA, CODCARGO, NOMCARGO, CENTRO_COSTO,
                            CODUNI, TELEFONO, CORREO, FICHA, FECINI, CODLOC, USRCRE, 
                            FECCRE, FECACT, ID_CAMBIO, OBSERVA
                        ) VALUES (
                            :cedula, :codigo_empresa, :codigo_cargo, :nombre_cargo, :centro_costo,
                            :unidad, :telefono, :correo, :ficha, TO_DATE(:fecha_inicio, 'YYYY-MM-DD'), 
                            :localidad, :usrcre, SYSDATE, SYSDATE, :id_cambio, :observa
                        )
                    """
                    cursor.execute(sql_laboral, {
                        "cedula": employee.cedula,
                        "codigo_empresa": employee.codigo_empresa,
                        "codigo_cargo": employee.codigo_cargo,
                        "nombre_cargo": employee.nombre_cargo,
                        "centro_costo": employee.centro_costo,
                        "unidad": employee.unidad_organizativa,
                        "telefono": employee.telefono_celular,
                        "correo": employee.correo_personal,
                        "ficha": employee.ficha,
                        "fecha_inicio": str(employee.fecha_inicio),
                        "localidad": employee.localidad,
                        "usrcre": settings.ETL_USER,
                        "id_cambio": settings.ETL_ID_CAMBIO,
                        "observa": settings.ETL_OBSERVA,
                    })

                    # 3. Inserción en TA_PARENTESCOS (Cargas Familiares)
                    sql_parentescos = """
                        INSERT INTO TA_PARENTESCOS (
                            CEDULA, NOMBRES, FECHA_NACIMIENTO, SEXO, PARENTESCO, 
                            USRCRE, FECCRE, FECACT, ID_CAMBIO, OBSERVA
                        ) VALUES (
                            :cedula, :nombres, TO_DATE(:fecha_nacimiento, 'YYYY-MM-DD'), 
                            :sexo, :parentesco, :usrcre, SYSDATE, SYSDATE, :id_cambio, :observa
                        )
                    """
                    for familiar in employee.cargas_familiares:
                        cursor.execute(sql_parentescos, {
                            "cedula": employee.cedula,
                            "nombres": familiar.nombres_apellidos,
                            "fecha_nacimiento": str(familiar.fecha_nacimiento),
                            "sexo": familiar.sexo,
                            "parentesco": familiar.tipo_parentesco,
                            "usrcre": settings.ETL_USER,
                            "id_cambio": settings.ETL_ID_CAMBIO,
                            "observa": settings.ETL_OBSERVA,
                        })

                # Commit definitivo si todas las sentencias tuvieron éxito
                conn.commit()
                logger.info(
                    "[OK] Insercion en cascada exitosa en SPI (Cedula: %s) con %d cargas familiares.",
                    employee.cedula, len(employee.cargas_familiares)
                )

            except Exception as e:
                # Rollback total ante cualquier falla
                conn.rollback()
                logger.error("[ERROR] Rollback desencadenado en transaccion de SPI para cedula %s: %s", employee.cedula, e)
                raise e


def get_oracle_dsn() -> str:
    """Construye el DSN (Data Source Name) para Oracle."""
    return oracledb.makedsn(
        host=settings.ORACLE_HOST,
        port=settings.ORACLE_PORT,
        service_name=settings.ORACLE_SERVICE_NAME,
    )


def get_oracle_connection() -> Mock:
    """
    Retorna conexión mock o real según configuración.
    """
    if settings.ORACLE_MOCK:
        logger.info("[MOCK] Conexion Oracle simulada (Mock)")
        return Mock()
    return oracledb.connect(
        user=settings.ORACLE_USER,
        password=settings.ORACLE_PASSWORD,
        dsn=get_oracle_dsn(),
    )


def test_oracle_connection() -> bool:
    """
    Verifica que la conexión a Oracle Database esté operativa.
    """
    try:
        if settings.ORACLE_MOCK:
            logger.info("[OK] Test de conexion a Oracle (MOCK): OK")
            return True
        conn = get_oracle_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM DUAL")
        cursor.close()
        conn.close()
        logger.info("[OK] Test de conexion a Oracle: OK")
        return True
    except (ConnectionError, Exception) as e:
        logger.error("[ERROR] Test de conexion a Oracle fallido: %s", e)
        return False
