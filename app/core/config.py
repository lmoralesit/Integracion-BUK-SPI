"""
Módulo de Configuración Centralizada DevSecOps (app.core.config).
Lee todas las variables de entorno sin permitir valores hardcodeados en la lógica.
"""
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # ── Infraestructura API ──
    APP_NAME: str = "ETL BUK-SPI DevSecOps"
    APP_VERSION: str = "1.0.0"
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000
    DEBUG: bool = False

    # ── Ciberseguridad Webhook (Mandamiento #4) ──
    BUK_WEBHOOK_SECRET: SecretStr = Field(..., description="Secreto HMAC / Bearer Token del Webhook de BUK")
    
    # ── BUK API REST (Mandamiento #1) ──
    BUK_API_BASE_URL: str = Field(..., description="Endpoint de la API REST de BUK, ej. https://alfonzorivas.buk.co/api/v1/colombia")
    BUK_API_TOKEN: SecretStr = Field(..., description="Token de autenticación de BUK")

    # ── SQL Server Staging (ODS) ──
    SQLSERVER_DRIVER: str = "{ODBC Driver 17 for SQL Server}"
    SQLSERVER_HOST: str = Field(..., description="Host y instancia de SQL Server, ej. localhost\\SQLEXPRESS")
    SQLSERVER_PORT: int = 1433
    SQLSERVER_DATABASE: str = "ETL_BUK_SPI"
    SQLSERVER_USER: str = "sa"
    SQLSERVER_PASSWORD: SecretStr = Field(...)

    # ── Oracle SPI (Capa Destino) ──
    ORACLE_HOST: str = "192.168.1.50"
    ORACLE_PORT: int = 1521
    ORACLE_SERVICE_NAME: str = "SPIPROD"
    ORACLE_USER: str = "SPI_ETL_USER"
    ORACLE_PASSWORD: SecretStr = Field(...)
    ORACLE_MOCK: bool = Field(default=True, description="Ejecuta en Mock durante desarrollo para no afectar nómina")

    # ── Auditoría SPI (RF-07) ──
    ETL_USER: str = "ETL"
    ETL_ID_CAMBIO: str = "10001"
    ETL_OBSERVA: str = "CREADO POR ETL"

    # ── Notificaciones SMTP ──
    SMTP_HOST: str = "aspmx.l.google.com"
    SMTP_PORT: int = 25
    SMTP_USER: str = "svc_etl_notifications@alfonzorivas.com"
    SMTP_PASSWORD: SecretStr = Field(default=SecretStr(""))
    SMTP_FROM: str = "svc_etl_notifications@alfonzorivas.com"
    SMTP_USE_TLS: bool = False

    NOTIFY_EMAIL_DEV: str = "lmorales@alfonzorivas.com"
    NOTIFY_EMAIL_CARACAS: str = "nomina_caracas@alfonzorivas.com"
    NOTIFY_EMAIL_TURMERO: str = "nomina_turmero@alfonzorivas.com"
    NOTIFY_EMAIL_RRHH: str = "capital_humano@alfonzorivas.com"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True

settings = Settings()
