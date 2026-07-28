-- ══════════════════════════════════════════════════════════════
-- Script:  04_crear_audit_log.sql
-- Proyecto: ETL BUK → SPI
-- Propósito: Tabla de Auditoría y Staging para Webhooks recibidos
--
-- Diccionario de Banderas de Estado (status_flag):
--   0 = Pendiente (Recibido por Webhook en cola)
--   1 = Procesado Exitosamente (Insertado en SPI y parcheado en BUK)
--   2 = Reintentando (Error intermitente de red/API, backoff en curso)
--   3 = Error de Localidad (Fallo por falta de equivalencia geográfica)
--   4 = Error de Validación Cía/Pre-existencia (Contrato abierto o empresa inválida)
-- ══════════════════════════════════════════════════════════════

USE ETL_BUK_SPI;
GO

IF NOT EXISTS (
    SELECT 1
    FROM   INFORMATION_SCHEMA.TABLES
    WHERE  TABLE_NAME = 'ETL_AUDIT_LOG'
)
BEGIN

    CREATE TABLE dbo.ETL_AUDIT_LOG
    (
        id                  INT             IDENTITY(1,1)   NOT NULL,
        employee_id         VARCHAR(50)     NOT NULL,
        event_type          VARCHAR(100)    NOT NULL,
        status_flag         INT             NOT NULL        DEFAULT 0,
        raw_payload         NVARCHAR(MAX)   NULL,
        error_message       NVARCHAR(MAX)   NULL,
        created_at          DATETIME        NOT NULL        DEFAULT GETDATE(),
        processed_at        DATETIME        NULL,

        CONSTRAINT PK_ETL_AUDIT_LOG PRIMARY KEY CLUSTERED (id)
    );

    CREATE NONCLUSTERED INDEX IX_AuditLog_StatusFlag
        ON dbo.ETL_AUDIT_LOG (status_flag)
        INCLUDE (employee_id, event_type, created_at);

    PRINT '✅ Tabla [ETL_AUDIT_LOG] creada exitosamente.';

END
ELSE
BEGIN
    PRINT '⚠️  La tabla [ETL_AUDIT_LOG] ya existe.';
END
GO
