# app/core/db.py
import logging
import time
from typing import Generator
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError, ProgrammingError, SQLAlchemyError
from sqlalchemy.orm import sessionmaker, Session
from app.core.config import settings

logger = logging.getLogger("DevSecOps.Database")

# =====================================================================
# 1. MOTOR Y POOL PARA STAGING / ODS (SQL SERVER)
# =====================================================================
# Mandamiento 3: Configuración de Pool Relacional Resiliente e Idempotente
staging_engine = create_engine(
    settings.sqlserver_url,
    pool_size=settings.SQLSERVER_POOL_SIZE,
    max_overflow=settings.SQLSERVER_MAX_OVERFLOW,
    pool_pre_ping=True,       # Verifica que el socket siga vivo antes de entregar sesión
    pool_recycle=3600,        # Recicla conexiones cada hora para evitar timeouts de firewall
    echo=False                # Mandamiento 5: NUNCA en True en Producción (previence fuga de PII)
)

StagingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=staging_engine)

# =====================================================================
# 2. MOTOR Y POOL PARA PRODUCCIÓN SPI INFOCENT (ORACLE DB)
# =====================================================================
oracle_engine = create_engine(
    settings.oracle_url,
    pool_size=settings.ORACLE_POOL_SIZE,
    max_overflow=settings.ORACLE_MAX_OVERFLOW,
    pool_pre_ping=True,
    pool_recycle=3600,
    echo=False
)

OracleSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=oracle_engine)


# =====================================================================
# 3. VERIFICACIÓN DE RESILIENCIA Y FAIL-FAST
# =====================================================================
def verify_db_connection_resilient(max_retries: int = 3, base_delay: float = 2.0) -> bool:
    """
    Mandamiento 2 & Patrón Fail-Fast:
    Verifica la conectividad con SQL Server Staging. Si el fallo es por credenciales (Error 18456),
    aborta inmediatamente sin reintentar para evitar bloqueo de cuentas en AD/SIEM.
    """
    for attempt in range(1, max_retries + 1):
        try:
            logger.debug(f"[SQLSERVER] Probando conectividad con Staging (Intento {attempt}/{max_retries})...")
            with staging_engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            logger.info("✅ Conexión a SQL Server (Staging/ODS) establecida y verificada.")
            
            # Verificación informativa de Oracle SPI (Respetando ORACLE_MOCK)
            if settings.ORACLE_MOCK:
                logger.info("🛡️ Oracle SPI configurado en modo MOCK (ORACLE_MOCK=True). No se tocará nómina real.")
            else:
                try:
                    with oracle_engine.connect() as o_conn:
                        o_conn.execute(text("SELECT 1 FROM DUAL"))
                    logger.info("✅ Conexión a Oracle DB (SPI Infocent) establecida y verificada.")
                except Exception as oe:
                    logger.warning(f"⚠️ Alerta: No se pudo verificar Oracle SPI en arranque: {str(oe)}")
            
            return True
            
        except OperationalError as e:
            error_msg = str(e)
            
            # 🚨 PATRÓN FAIL-FAST: Detectar errores fatales de autenticación (SQL State 28000 / Error 18456)
            if "18456" in error_msg or "28000" in error_msg or "Login failed" in error_msg:
                logger.critical(
                    "🔥 FALLO FATAL DE AUTENTICACIÓN EN SQL SERVER (Error 18456). "
                    "Credenciales inválidas o Modo Mixto deshabilitado. Abortando (Fail-Fast)."
                )
                return False
            
            if attempt == max_retries:
                logger.critical(f"❌ Agotados los {max_retries} intentos de conexión a SQL Server: {error_msg}")
                return False
                
            sleep_time = base_delay * (2 ** (attempt - 1))  # Exponential Backoff
            logger.warning(
                f"⚠️ Error transitorio al conectar a SQL Server. Reintentando en {sleep_time}s... "
                f"({error_msg.splitlines()[0]})"
            )
            time.sleep(sleep_time)
            
        except Exception as e:
            logger.critical(f"🔥 Error inesperado en capa relacional Staging: {str(e)}")
            return False
            
    return False


# =====================================================================
# 4. GENERADORES DE INYECCIÓN DE DEPENDENCIAS (FASTAPI)
# =====================================================================
def get_staging_db() -> Generator[Session, None, None]:
    """
    Mandamiento 3 & 4: Inyección de dependencias para SQL Server Staging / ODS.
    Garantiza el cierre limpio del socket y Rollback automático ante excepciones DML.
    """
    db = StagingSessionLocal()
    try:
        yield db
    except Exception as e:
        logger.error("🚨 Rollback automático en SQL Server Staging por excepción en transacción.")
        db.rollback()
        raise
    finally:
        db.close()

# Alias de compatibilidad hacia atrás por si otros routers importan 'get_db'
get_db = get_staging_db

def get_oracle_db() -> Generator[Session, None, None]:
    """
    Mandamiento 3 & 4: Inyección de dependencias para Oracle DB (SPI Infocent).
    Garantiza aislamiento transaccional y Rollback ante fallos de inserción en nómina.
    """
    db = OracleSessionLocal()
    try:
        yield db
    except Exception as e:
        logger.error("🚨 Rollback automático en Oracle SPI por excepción en transacción.")
        db.rollback()
        raise
    finally:
        db.close()

# Alias para nomenclatura de negocio SPI
get_spi_db = get_oracle_db