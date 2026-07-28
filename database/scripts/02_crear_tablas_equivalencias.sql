-- ══════════════════════════════════════════════════════════════
-- Script:  02_crear_tablas_equivalencias.sql
-- Proyecto: ETL BUK → SPI
-- Propósito: Crear la tabla de equivalencias maestras en la capa
--            de Staging (SQL Server) para centralizar los reemplazos
--            de campos como Estado Civil, Ciudad, etc.
-- ══════════════════════════════════════════════════════════════

IF NOT EXISTS (
    SELECT 1
    FROM   INFORMATION_SCHEMA.TABLES
    WHERE  TABLE_NAME = 'ETL_BUK_Equivalencias'
)
BEGIN
    CREATE TABLE dbo.ETL_BUK_Equivalencias
    (
        ID_Equivalencia INT IDENTITY(1,1) NOT NULL,
        Tipo_Dato       VARCHAR(50)       NOT NULL,
        Valor_BUK       VARCHAR(100)      NOT NULL,
        Codigo_SPI      VARCHAR(50)       NOT NULL,

        CONSTRAINT PK_ETL_BUK_Equivalencias PRIMARY KEY CLUSTERED (ID_Equivalencia)
    );

    PRINT '✅ Tabla [ETL_BUK_Equivalencias] creada exitosamente.';

    --
    -- ── DATOS SEMILLA ──
    -- Ejemplo: BUK envía el estado civil como palabra completa,
    -- pero SPI espera solo un carácter.
    --
    INSERT INTO dbo.ETL_BUK_Equivalencias (Tipo_Dato, Valor_BUK, Codigo_SPI)
    VALUES 
        ('ESTADO_CIVIL', 'Soltero', 'S'),
        ('ESTADO_CIVIL', 'Casado', 'C'),
        ('ESTADO_CIVIL', 'Divorciado', 'D'),
        ('ESTADO_CIVIL', 'Viudo', 'V');
        
    PRINT '🌱 Datos semilla insertados en [ETL_BUK_Equivalencias].';
END
ELSE
BEGIN
    PRINT '⚠️  La tabla [ETL_BUK_Equivalencias] ya existe en la base de datos. Saltando creación.';
END
GO
