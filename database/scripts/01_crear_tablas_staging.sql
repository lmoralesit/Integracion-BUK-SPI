-- ══════════════════════════════════════════════════════════════
-- Script:  01_crear_tablas_staging.sql
-- Proyecto: ETL BUK → SPI
-- Propósito: Crear la tabla de control de ingresos en la BD
--            intermedia (Staging) de SQL Server.
-- Autor:   ETL Team
-- Fecha:   2026-07-08
-- ══════════════════════════════════════════════════════════════

-- ──────────────────────────────────────────────
-- Tabla: ETL_BUK_Control_Ingresos
-- Descripción: Registra cada webhook recibido de BUK,
--   almacena el JSON crudo, la ficha asignada y el
--   estado de procesamiento para auditoría y reproceso.
--
-- Diccionario de Banderas de Estado (Status_Code):
--   0 = Pendiente (recién recibido, sin procesar)
--   1 = Procesado Exitosamente
--   2 = Procesado con Advertencias
--   3 = Error de Inconsistencia de Datos
--   4 = Error Societario (empresa no válida)
--   5 = Error de Conexión a Oracle/SPI
--   9 = Descartado / Duplicado
-- ──────────────────────────────────────────────

IF NOT EXISTS (
    SELECT 1
    FROM   INFORMATION_SCHEMA.TABLES
    WHERE  TABLE_NAME = 'ETL_BUK_Control_Ingresos'
)
BEGIN

    CREATE TABLE dbo.ETL_BUK_Control_Ingresos
    (
        -- Identificador único autoincremental
        ID_Transaccion      INT             IDENTITY(1,1)   NOT NULL,

        -- Momento exacto en que la API recibió el webhook
        Fecha_Recepcion     DATETIME        NOT NULL        DEFAULT GETDATE(),

        -- JSON crudo completo enviado por BUK (sin transformar)
        Payload_JSON        NVARCHAR(MAX)   NOT NULL,

        -- Ficha correlativa asignada al empleado (se llena post-reserva)
        Ficha_Asignada      VARCHAR(20)     NULL,

        -- Cédula del empleado (para búsquedas rápidas y validación de duplicados)
        Cedula_Empleado     VARCHAR(20)     NULL,

        -- Bandera de estado del procesamiento ETL (ver diccionario arriba)
        Status_Code         INT             NOT NULL        DEFAULT 0,

        -- Detalle del error si Status_Code >= 3
        Mensaje_Error       NVARCHAR(MAX)   NULL,

        -- Fecha en que se completó el procesamiento (éxito o error final)
        Fecha_Procesamiento DATETIME        NULL,

        -- Constraint: clave primaria
        CONSTRAINT PK_ETL_BUK_Control_Ingresos
            PRIMARY KEY CLUSTERED (ID_Transaccion)
    );

    -- Índice para búsquedas por estado (reproceso de pendientes/errores)
    CREATE NONCLUSTERED INDEX IX_StatusCode
        ON dbo.ETL_BUK_Control_Ingresos (Status_Code)
        INCLUDE (Fecha_Recepcion, Cedula_Empleado);

    -- Índice para validar duplicados por cédula
    CREATE NONCLUSTERED INDEX IX_Cedula
        ON dbo.ETL_BUK_Control_Ingresos (Cedula_Empleado)
        INCLUDE (Status_Code, Fecha_Recepcion);

    PRINT '✅ Tabla [ETL_BUK_Control_Ingresos] creada exitosamente.';

END
ELSE
BEGIN
    PRINT '⚠️  La tabla [ETL_BUK_Control_Ingresos] ya existe. No se realizaron cambios.';
END
GO
