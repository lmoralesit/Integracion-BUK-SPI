# app/core/config.py
import re
from pathlib import Path
from typing import Optional
from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Obtener la raíz absoluta del repositorio (subiendo 2 niveles desde app/core/)
ROOT_DIR = Path(__file__).resolve().parent.parent.parent

class Settings(BaseSettings):
    """
    Mandamiento 1 (Security by Design):
    Centralización y validación estricta de variables de entorno.
    Uso de SecretStr para prevenir fugas de PII/Secretos en logs operativos.
    """
    
    # ---------------------------------------------------------------------------
    # 1. APLICACIÓN Y SERVIDOR
    # ---------------------------------------------------------------------------
    APP_NAME: str = Field(default="ETL BUK-SPI DevSecOps")
    APP_VERSION: str = Field(default="1.0.0")
    APP_ENV: str = Field(default="development")
    APP_HOST: str = Field(default="127.0.0.1")
    APP_PORT: int = Field(default=8000, ge=1024, le=65535)
    DEBUG: bool = Field(default=True)
    WORKERS_COUNT: int = Field(default=2, ge=1, le=16)
    
    # ---------------------------------------------------------------------------
    # 2. SEGURIDAD Y WEBHOOKS (BUK)
    # ---------------------------------------------------------------------------
    BUK_API_BASE_URL: str = Field(...)
    BUK_API_TOKEN: SecretStr = Field(...)       # Blindado en logs
    BUK_WEBHOOK_SECRET: SecretStr = Field(...)  # Blindado en logs
    
    # ---------------------------------------------------------------------------
    # 3. RESILIENCIA HTTP (httpx)
    # ---------------------------------------------------------------------------
    HTTP_TIMEOUT_SECONDS: int = Field(default=15, ge=5)
    HTTP_MAX_RETRIES: int = Field(default=3, ge=1)
    HTTP_BACKOFF_FACTOR: float = Field(default=1.5, gt=0)
    
    # ---------------------------------------------------------------------------
    # 4. SQL SERVER (STAGING / ODS)
    # ---------------------------------------------------------------------------
    SQLSERVER_DRIVER: str = Field(...)
    SQLSERVER_HOST: str = Field(...)
    SQLSERVER_PORT: int = Field(default=1433)
    SQLSERVER_DATABASE: str = Field(...)
    SQLSERVER_USER: str = Field(...)
    SQLSERVER_PASSWORD: SecretStr = Field(...)  # Blindado en logs
    SQLSERVER_POOL_SIZE: int = Field(default=10)
    SQLSERVER_MAX_OVERFLOW: int = Field(default=5)
    
    # ---------------------------------------------------------------------------
    # 5. ORACLE DB (SPI INFOCENT)
    # ---------------------------------------------------------------------------
    ORACLE_MOCK: bool = Field(default=True)
    ORACLE_HOST: str = Field(...)
    ORACLE_PORT: int = Field(default=1521)
    ORACLE_SERVICE_NAME: str = Field(...)
    ORACLE_USER: str = Field(...)
    ORACLE_PASSWORD: SecretStr = Field(...)     # Blindado en logs
    ORACLE_POOL_SIZE: int = Field(default=5)
    ORACLE_MAX_OVERFLOW: int = Field(default=5)
    
    # ---------------------------------------------------------------------------
    # 6. AUDITORÍA Y REGLAS SPI
    # ---------------------------------------------------------------------------
    ETL_USER: str = Field(default="ETL")
    ETL_ID_CAMBIO: str = Field(default="10001")
    ETL_OBSERVA: str = Field(default="CREADO POR ETL")
    SPI_DEFAULT_COUNTRY: str = Field(default="VEN")
    SPI_DEFAULT_MOTIVO: str = Field(default="NI")
    SPI_MAX_PUESTO_LEN: int = Field(default=36)
    
    # ---------------------------------------------------------------------------
    # 7. SISTEMA DE NOTIFICACIONES (SMTP)
    # ---------------------------------------------------------------------------
    SMTP_HOST: str = Field(...)
    SMTP_PORT: int = Field(default=25)
    SMTP_USER: Optional[str] = Field(default=None)
    SMTP_PASSWORD: Optional[SecretStr] = Field(default=None)
    SMTP_FROM: str = Field(...)
    SMTP_USE_TLS: bool = Field(default=False)
    
    # ---------------------------------------------------------------------------
    # 8. MATRIZ DE ENRUTAMIENTO DE CORREOS
    # ---------------------------------------------------------------------------
    MAIL_TO_DEV: str = Field(...)
    MAIL_TO_CAPITAL_HUMANO: str = Field(...)
    MAIL_TO_NOMINA_CARACAS: str = Field(...)
    MAIL_TO_NOMINA_TURMERO: str = Field(...)

    # ---------------------------------------------------------------------------
    # VALIDADORES Y SANITIZADORES DE SEGURIDAD
    # ---------------------------------------------------------------------------
    @model_validator(mode="after")
    def validate_network_exposure(self) -> "Settings":
        """
        Bloquea la exposición insegura de interfaces en entornos no productivos.
        """
        if self.APP_ENV.lower() == "development" and self.APP_HOST == "0.0.0.0":
            raise ValueError(
                "🚨 ALERTA DEVSECOPS: Prohibido bindear a 0.0.0.0 con APP_ENV='development'. "
                "Cambia APP_HOST a '127.0.0.1' en tu archivo .env para desarrollo local."
            )
        return self

    @field_validator(
        "MAIL_TO_DEV", 
        "MAIL_TO_CAPITAL_HUMANO", 
        "MAIL_TO_NOMINA_CARACAS", 
        "MAIL_TO_NOMINA_TURMERO", 
        mode="before"
    )
    @classmethod
    def sanitize_and_validate_emails(cls, value: str, info) -> str:
        """
        Previene inyecciones SMTP (OWASP A03) bloqueando saltos de línea CRLF
        y valida el formato sintáctico del correo RFC 5322.
        """
        if not value or not isinstance(value, str):
            raise ValueError(f"El campo {info.field_name} es obligatorio.")
            
        if "\r" in value or "\n" in value:
            raise ValueError(f"🚨 ALERTA DE SEGURIDAD: Intento de inyección CRLF en {info.field_name}.")
            
        emails = [email.strip() for email in value.split(",") if email.strip()]
        email_regex = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")
        
        for email in emails:
            if not email_regex.match(email):
                raise ValueError(f"Dirección de correo inválida: '{email}' en el campo {info.field_name}.")
                
        return value

    @property
    def sqlserver_url(self) -> str:
        """Genera Connection String seguro para SQL Server codificando caracteres especiales."""
        import urllib.parse
        user = urllib.parse.quote_plus(self.SQLSERVER_USER)
        pwd = urllib.parse.quote_plus(self.SQLSERVER_PASSWORD.get_secret_value())
        host = urllib.parse.quote_plus(self.SQLSERVER_HOST)
        db = urllib.parse.quote_plus(self.SQLSERVER_DATABASE)
        driver = urllib.parse.quote_plus(self.SQLSERVER_DRIVER)
        return f"mssql+pyodbc://{user}:{pwd}@{host}:{self.SQLSERVER_PORT}/{db}?driver={driver}"

    @property
    def oracle_url(self) -> str:
        """Genera Connection String seguro para Oracle DB codificando caracteres especiales."""
        import urllib.parse
        user = urllib.parse.quote_plus(self.ORACLE_USER)
        pwd = urllib.parse.quote_plus(self.ORACLE_PASSWORD.get_secret_value())
        host = urllib.parse.quote_plus(self.ORACLE_HOST)
        service = urllib.parse.quote_plus(self.ORACLE_SERVICE_NAME)
        return f"oracle+oracledb://{user}:{pwd}@{host}:{self.ORACLE_PORT}/?service_name={service}"

    model_config = SettingsConfigDict(
        env_file=str(ROOT_DIR / ".env"),  # Ruta absoluta garantizada
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="forbid"  # Prevención estricta de Schema Drift y variables extrañas
    )

settings = Settings()