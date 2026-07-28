-- ══════════════════════════════════════════════════════════════
-- Script:  03_crear_tablas_ods.sql
-- Proyecto: ETL BUK → SPI
-- Propósito: Crear tablas normalizadas ODS para cruces
-- ══════════════════════════════════════════════════════════════
USE ETL_BUK_SPI;
GO

IF OBJECT_ID('dbo.ETL_BUK_ODS_Trabajo', 'U') IS NOT NULL
BEGIN
    DROP TABLE dbo.ETL_BUK_ODS_Trabajo;
    PRINT 'Tabla ETL_BUK_ODS_Trabajo eliminada.';
END
GO

IF OBJECT_ID('dbo.ETL_BUK_ODS_Personal', 'U') IS NOT NULL
BEGIN
    DROP TABLE dbo.ETL_BUK_ODS_Personal;
    PRINT 'Tabla ETL_BUK_ODS_Personal eliminada.';
END
GO

CREATE TABLE dbo.ETL_BUK_ODS_Personal
(
    ID_Empleado       INT PRIMARY KEY,
    Ficha             VARCHAR(20),
    Cedula            VARCHAR(20),
    RIF               VARCHAR(20),
    Nombres           VARCHAR(100),
    Apellidos         VARCHAR(100),
    Email             VARCHAR(100),
    Telefono          VARCHAR(50),
    Fecha_Nacimiento  DATE,
    Estado_Civil      VARCHAR(50),
    Genero            VARCHAR(20),
    Nacionalidad      VARCHAR(50),
    Direccion         VARCHAR(255),
    Ciudad            VARCHAR(100),
    Estado            VARCHAR(100)
);
PRINT '✅ Tabla [ETL_BUK_ODS_Personal] creada exitosamente.';

CREATE TABLE dbo.ETL_BUK_ODS_Trabajo
(
    ID_Trabajo        INT PRIMARY KEY,
    ID_Empleado       INT,
    Company_ID        VARCHAR(20),
    Fecha_Ingreso     DATE,
    Cargo_Nombre      VARCHAR(150),
    Centro_Costo      VARCHAR(50),
    Sede              VARCHAR(100)
);
PRINT '✅ Tabla [ETL_BUK_ODS_Trabajo] creada exitosamente.';
GO
