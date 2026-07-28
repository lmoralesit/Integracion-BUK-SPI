-- ==============================================================================
-- SCRIPT MAESTRO DDL: ESTANDARIZACIÓN STAGING ETL BUK-SPI
-- MOTOR: SQL Server 2019/2022 | ARQUITECTURA: DevSecOps Idempotente
-- ==============================================================================

USE [master];
GO

IF NOT EXISTS (SELECT name FROM sys.databases WHERE name = N'ETL_BUK_SPI')
BEGIN
    CREATE DATABASE [ETL_BUK_SPI];
    PRINT '✅ Base de datos [ETL_BUK_SPI] creada exitosamente.';
END
GO

USE [ETL_BUK_SPI];
GO

-- ------------------------------------------------------------------------------
-- PASO 0: LIMPIEZA DE TABLAS REDUNDANTES O DUPLICADAS (DEPRECATION CLEAN-UP)
-- Eliminamos el rastro de arquitecturas duales previas para evitar colisiones.
-- ------------------------------------------------------------------------------
IF OBJECT_ID('dbo.ETL_BUK_Control_Ingresos', 'U') IS NOT NULL
BEGIN
    DROP TABLE dbo.ETL_BUK_Control_Ingresos;
    PRINT '🗑️ Tabla legada [ETL_BUK_Control_Ingresos] eliminada (Unificada en ETL_AUDIT_LOG).';
END

IF OBJECT_ID('dbo.ETL_EQUIVALENCIAS', 'U') IS NOT NULL
BEGIN
    DROP TABLE dbo.ETL_EQUIVALENCIAS;
    PRINT '🗑️ Tabla duplicada [ETL_EQUIVALENCIAS] eliminada (Unificada en ETL_BUK_Equivalencias).';
END

IF OBJECT_ID('dbo.ETL_Correlativo_Ficha', 'U') IS NOT NULL
BEGIN
    DROP TABLE dbo.ETL_Correlativo_Ficha;
    PRINT '🗑️ Tabla legada [ETL_Correlativo_Ficha] eliminada (Unificada en ETL_CORRELATIVOS).';
END

IF OBJECT_ID('dbo.ETL_BUK_ODS_Personal', 'U') IS NOT NULL
BEGIN
    DROP TABLE dbo.ETL_BUK_ODS_Personal;
    PRINT '🗑️ Tabla temporal [ETL_BUK_ODS_Personal] eliminada.';
END

IF OBJECT_ID('dbo.ETL_BUK_ODS_Trabajo', 'U') IS NOT NULL
BEGIN
    DROP TABLE dbo.ETL_BUK_ODS_Trabajo;
    PRINT '🗑️ Tabla temporal [ETL_BUK_ODS_Trabajo] eliminada.';
END
GO

-- ------------------------------------------------------------------------------
-- 1. TABLA CORE: ETL_AUDIT_LOG (ODS, Cola del Worker y Log Visual del Dashboard)
-- ------------------------------------------------------------------------------
IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'ETL_AUDIT_LOG')
BEGIN
    CREATE TABLE dbo.ETL_AUDIT_LOG (
        id                  INT             IDENTITY(1,1)   NOT NULL,
        employee_id         VARCHAR(50)     NOT NULL,
        event_type          VARCHAR(100)    NOT NULL,
        status_flag         INT             NOT NULL        DEFAULT 0, -- 0=Pendiente, 1=OK, 2=Reintentando, 3=Err Datos, 4=Pre-existencia
        raw_payload         NVARCHAR(MAX)   NULL,
        error_message       NVARCHAR(MAX)   NULL,
        created_at          DATETIME        NOT NULL        DEFAULT GETDATE(),
        processed_at        DATETIME        NULL,
        updated_at          DATETIME        NOT NULL        DEFAULT GETDATE(),
        CONSTRAINT PK_ETL_AUDIT_LOG PRIMARY KEY CLUSTERED (id)
    );

    CREATE NONCLUSTERED INDEX IX_AuditLog_StatusFlag 
        ON dbo.ETL_AUDIT_LOG (status_flag) 
        INCLUDE (employee_id, event_type, created_at);

    PRINT '✅ Tabla principal [ETL_AUDIT_LOG] creada con sus índices.';
END
GO

-- ------------------------------------------------------------------------------
-- 2. TABLA CORE: ETL_CORRELATIVOS (Reserva Atómica de Fichas RF-01)
-- ------------------------------------------------------------------------------
IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'ETL_CORRELATIVOS')
BEGIN
    CREATE TABLE dbo.ETL_CORRELATIVOS (
        empresa_id NVARCHAR(10) NOT NULL PRIMARY KEY,
        u_ficha    INT          NOT NULL
    );

    -- Semillas de correlativos para concurrencia con bloqueos UPDLOCK
    INSERT INTO dbo.ETL_CORRELATIVOS (empresa_id, u_ficha) 
    VALUES ('D6', 100), ('TUR', 500), ('DEFAULT', 1000);

    PRINT '✅ Tabla [ETL_CORRELATIVOS] inicializada con semillas corporativas.';
END
GO

-- ------------------------------------------------------------------------------
-- 3. TABLA CORE: ETL_BUK_Equivalencias (Matriz de Homologación BUK -> SPI)
-- ------------------------------------------------------------------------------
IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'ETL_BUK_Equivalencias')
BEGIN
    CREATE TABLE dbo.ETL_BUK_Equivalencias (
        ID_Equivalencia INT IDENTITY(1,1) NOT NULL,
        Tipo_Dato       VARCHAR(50)       NOT NULL,
        Valor_BUK       VARCHAR(100)      NOT NULL,
        Codigo_SPI      VARCHAR(50)       NOT NULL,
        CONSTRAINT PK_ETL_BUK_Equivalencias PRIMARY KEY CLUSTERED (ID_Equivalencia)
    );

    -- Semillas según Reglas de Negocio del Contexto y tablas NMT/EO de SPI
    INSERT INTO dbo.ETL_BUK_Equivalencias (Tipo_Dato, Valor_BUK, Codigo_SPI) VALUES 
        ('ESTADO_CIVIL', 'Soltero', '1'),
        ('ESTADO_CIVIL', 'Casado', '2'),
        ('ESTADO_CIVIL', 'Divorciado', '3'),
        ('ESTADO_CIVIL', 'Viudo', '4'),
        ('SEXO', 'M', 'M'),
        ('SEXO', 'F', 'F'),
        ('EMPRESA', 'D6', 'D6'),
        ('EMPRESA', 'TUR', 'TUR'),
        ('LOCALIDAD', 'Caracas', 'CCS'),
        ('LOCALIDAD', 'Turmero', 'TUR');

    PRINT '✅ Tabla [ETL_BUK_Equivalencias] inicializada con semillas.';
END
GO