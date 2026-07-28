-- ══════════════════════════════════════════════════════════════
-- Script:  02_crear_correlativos_ficha.sql
-- Proyecto: ETL BUK → SPI
-- Propósito: Crear la tabla de correlativos para generar la ficha autoincremental (RF-01)
-- ══════════════════════════════════════════════════════════════

USE ETL_BUK_SPI;
GO

IF NOT EXISTS (
    SELECT 1
    FROM   INFORMATION_SCHEMA.TABLES
    WHERE  TABLE_NAME = 'ETL_CORRELATIVOS'
)
BEGIN
    CREATE TABLE [dbo].[ETL_CORRELATIVOS](
        [empresa_id] [nvarchar](10) PRIMARY KEY,
        [u_ficha] [int] NOT NULL
    );

    INSERT INTO [dbo].[ETL_CORRELATIVOS] (empresa_id, u_ficha) 
    VALUES ('D6', 100), ('DEFAULT', 100);

    PRINT '✅ Tabla [ETL_CORRELATIVOS] creada exitosamente.';
END
ELSE
BEGIN
    PRINT '⚠️  La tabla [ETL_CORRELATIVOS] ya existe.';
END
GO
