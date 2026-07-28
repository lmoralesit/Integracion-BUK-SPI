# Contexto del Proyecto: Integración ETL BUK - SPI

## 1. Visión General
Desarrollo desde cero de una interfaz automatizada de extracción, transformación y carga (ETL).
* **Origen:** BUK (Sistema de gestión de capital humano en la nube).
* **Destino:** SPI / Infocent (Sistema de nómina local).
* **Prioridad Actual:** Módulo de Nuevos Ingresos de Personal (Onboarding).

---

## 2. Arquitectura, Stack Técnico y Despliegue
* **Lenguaje:** Python 3.10+.
* **Framework Web:** FastAPI (recepción de Webhooks BUK en tiempo real y panel admin visual).
* **Capa Intermedia (Staging / ODS):** SQL Server (vía `pyodbc` con Autenticación Windows / ODBC Driver 17) para alojar datos JSON recibidos, correlativos atómicos, tablas de control, auditoría (`ETL_AUDIT_LOG`) y equivalencias (`ETL_BUK_Equivalencias`).
* **Capa Destino:** Oracle Database (vía `oracledb` en modo thin) interactuando mediante sentencias SQL parametrizadas en tablas relacionales de SPI (`EO_PERSONA`, `TA_RELACION_LABORAL`, `TA_RELACION_PUESTO`, `TA_PARENTESCOS`). Incluye soporte de simulación `ORACLE_MOCK` con `MagicMock`.
* **Seguridad (DevSecOps):** Autenticación de Webhooks mediante firmas criptográficas HMAC-SHA256 (`X-Buk-Signature`) y Bearer Tokens evaluados en tiempo constante con `hmac.compare_digest` para evitar Timing Attacks (OWASP Top 10). Protección de secretos mediante `Pydantic SecretStr`.
* **Cliente HTTP:** `httpx` asíncrono con reintentos exponenciales y backoff.
* **Alertas SMTP:** Notificaciones automatizadas por correo HTML (`smtplib`) diferenciadas para Nómina (Éxito) y Capital Humano (Errores de pre-existencia / inconsistencia).
* **Infraestructura:** Ejecución local/servidor compartiendo red interna con SPI y SQL Server, con peticiones salientes HTTPS a la API de BUK. Despliegue objetivo en Windows Server (2019/2022).

---

## 3. Estado de Desarrollo y Componentes Construidos

### 3.1 Módulo Core y Configuración (`app/config.py`, `app/core/config.py`, `app/core/security.py`, `.env`)
- **Gestión de Configuración (`app/core/config.py`):** `Pydantic BaseSettings` con `SecretStr` para centralizar credenciales, URLs de BUK API, tokens, llaves HMAC y contraseñas de bases de datos. Re-exportado en `app/config.py` para compatibilidad de importaciones.
- **Seguridad Webhook (`app/core/security.py`):** Dependencia `verify_buk_signature` que valida en tiempo constante la cabecera `X-Buk-Signature` (HMAC-SHA256) o el Bearer Token contra `settings.BUK_WEBHOOK_SECRET`.

### 3.2 Capa de Datos y Scripts DDL (`database/scripts/`, `app/database/`)
- `00_schema_maestro_devsecops.sql`: DDL Maestro e Idempotente que estandariza la base de datos `ETL_BUK_SPI`:
  - `ETL_AUDIT_LOG`: Tabla principal de auditoría y cola ODS (`id`, `employee_id`, `event_type`, `status_flag`, `raw_payload`, `error_message`, `created_at`, `processed_at`, `updated_at`).
  - `ETL_CORRELATIVOS`: Tabla para reserva atómica de fichas corporativas por empresa (`D6`, `TUR`, `DEFAULT`) con bloqueos `UPDLOCK, ROWLOCK`.
  - `ETL_BUK_Equivalencias`: Matriz de homologación (`ESTADO_CIVIL`, `SEXO`, `EMPRESA`, `LOCALIDAD`).
- `app/database/sql_server.py`: Conector ODBC resiliente a Staging (`get_sqlserver_connection`) y generador atómico de correlativos (`get_next_atomic_ficha`).
- `app/database/oracle.py`: Conector transaccional a Oracle SPI con soporte de modo Mock (`MagicMock`).

### 3.3 Motor ETL y Saneamiento (`app/services/`, `app/utils/`)
- **Cliente BUK (`app/services/buk_client.py`):** `BukAPIClient` asíncrono para peticiones GET `/employees/{id}` con retries exponenciales y solicitudes PATCH para sincronizar la Ficha autogenerada en BUK.
- **Transformadores (`app/utils/transformers.py`):**
  - Sanitización RIF (`formatear_rif`): Limpieza de guiones/puntos y formato en mayúscula (ej. `V12345678`).
  - Depuración de Nombres (`sanitizar_nombre`): Eliminación de acentos/tildes (`unicodedata`).
  - Sanitización de Cargos (`truncar_codigo_cargo`): Eliminación del `.0` residual exportado por BUK.
  - Puestos SPI (`format_spi_position`): Truncado estricto a máximo 36 caracteres (RF-02).
  - Valores neutros (`ensure_not_null`): Relleno (`.` / `-`) en campos requeridos por SPI.
  - Herencia de Lugar de Nacimiento (`heredar_lugar_nacimiento`) desde dirección de residencia.
- **Pipeline ETL Background (`app/services/etl_engine.py`):**
  - Orquestador asíncrono `execute_etl_pipeline`.
  - Reserva atómica de ficha en SQL Server.
  - Salvaguarda de Pre-existencia Laboral (RF-05): Verificación de contrato abierto activo en SPI.
  - Inserción transaccional parametrizada en SPI (`EO_PERSONA`, `TA_RELACION_LABORAL`, `TA_RELACION_PUESTO`) con auditoría obligatoria (`Usrcre="ETL"`, `Id_cambio="10001"`, `OBSERVA="CREADO POR ETL"`).
  - Actualización de `ETL_AUDIT_LOG` (`status_flag`, `processed_at`, `updated_at`) y parche de Ficha en BUK.
- **Worker en Segundo Plano (`app/services/worker.py`):** Polling asíncrono (`ETLWorker`) que sondea registros con `status_flag = 0` para ejecución continua.
- **Notificador SMTP (`app/services/notifier.py`):** `EmailNotifier` para enviar alertas por correo HTML a Nómina (Éxito) y Capital Humano (Errores de validación / pre-existencia).

### 3.4 API Endpoints y Panel Admin Visual (`app/api/endpoints/`, `app/templates/`)
- **Webhook (`app/api/endpoints/webhook.py`):** Endpoint POST `/api/v1/buk/employee` (y alias `/webhook/buk`) con seguridad HMAC previa (`Depends(verify_buk_signature)`), inserción parametrizada en `ETL_AUDIT_LOG` y respuesta instantánea `HTTP 202 Accepted`.
- **Panel Admin (`app/api/endpoints/admin.py` & `dashboard.html`):**
  - Vista `/admin/dashboard` en Tailwind CSS + Jinja2 que renderiza los últimos 50 eventos ODS.
  - Aplanamiento de datos en Python para evitar incompatibilidades Jinja2.
  - Compatibilidad estricta con Starlette 0.28+ usando argumentos nominados (`request=request, name="dashboard.html", context={...}`).
  - Endpoint `/admin/retry/{audit_id}` para relanzamiento manual de tareas fallidas.

### 3.5 Diagnostic & Test Suite (`test_webhook_e2e.py`, `test_api_extraccion.py`)
- `test_webhook_e2e.py`: Suite E2E con generación de firmas HMAC-SHA256 desde `.env`, prueba de alta normal (Flag 1) y prueba de salvaguarda de pre-existencia laboral (Flag 4).
- `test_api_extraccion.py`: Script de diagnóstico saliente para probar extracción real desde la API de BUK y verificar la sanitización previa a Oracle SPI.

---

## 4. Reglas de Negocio y Transformación (Requerimientos Funcionales)
* **Gestión de Fichas:** Reservar correlativos en SQL Server de forma atómica (`UPDLOCK, ROWLOCK`) e inyectar la ficha automáticamente en BUK vía PATCH.
* **Depuración de Cargos:** Truncar el `.0` de los códigos de cargo provenientes de BUK. El campo Puesto en SPI está limitado a un máximo de 36 caracteres.
* **Pre-existencia Laboral (Crítico RF-05):** Buscar la Cédula en `EO_PERSONA` antes de procesar el alta. Frenar la inserción si la relación laboral anterior en `TA_RELACION_LABORAL` sigue abierta sin fecha de fin (Flag 4).
* **Auditoría Técnica Obligatoria (RF-07):** Toda inserción en `TA_RELACION_LABORAL`, `TA_RELACION_PUESTO`, `EO_CARGO`, `EO_PUESTO` y `EO_UNIDAD` debe incluir mandatoriamente: `Usrcre = "ETL"`, `Feccre` y `Fecact` con fecha del sistema, `Id_cambio = "10001"`, y `OBSERVA = "CREADO POR ETL"`.
* **Derivación de Empresa:** Extraer el código de empresa de `custom_attributes.codigo_empresa` de BUK.
* **Formateo y Sanitización:**
  * Limpiar RIF eliminando guiones/puntos y anteponer letra en mayúscula (ej. `V145758120`).
  * Sanitizar cadenas de nombres removiendo tildes/acentos.
* **Valores Neutros:** Si teléfono o correo están vacíos, insertar carácter neutro (`.` o `-`) requerido por SPI.
* **Lugar de Nacimiento:** Heredar desde los campos de dirección de residencia actual.

---

## 5. Módulo Administrativo Visual (Regla Estricta)
* Prohibido el uso de parámetros hardcoded en el código (centralizados en `.env` + `Pydantic BaseSettings`).
* Panel visual para auditar el procesamiento mediante el diccionario de Banderas de Estado:
  * `0` = Pendiente (Recibido por Webhook en cola ODS)
  * `1` = Procesado Exitosamente (Insertado en SPI y parcheado en BUK)
  * `2` = Reintentando (Error intermitente de red/API)
  * `3` = Error de Localidad / Datos (Inconsistencias)
  * `4` = Error de Validación Cía / Pre-existencia (Contrato abierto activo en SPI)

---

## 6. Matriz de Mapeo Principal (BUK -> SQL Server -> SPI)

| Campos Origen (BUK) | Tablas Destino (SPI) | Regla / Transformación |
| :--- | :--- | :--- |
| Datos Personales, Teléfono, Correo, RIF | `ANAGPERS`, `EO_PERSONA` | Sanitización acentos, RIF mayúscula sin guiones, valores neutros (`.`/`-`) en nulos. |
| Dirección de Habitación | `TB_COMUNE`, `SPI_ENTIDAD_FEDERAL` | Tabla de equivalencias SQL Server. Hereda a lugar nacimiento. |
| Ficha, F. Inicio, Antigüedad, Estado | `COMPREL`, `TA_RELACION_LABORAL` | Campos técnicos obligatorios (`Usrcre="ETL"`). Empresa vía `custom_attributes`. |
| Unidad, Puesto, Centro de Costo | `INCARLAV`, `TA_RELACION_PUESTO` | Puesto límite 36 caracteres, truncar `.0` cargos, `Id_cambio="10001"`. |
| Carga Familiar (Nombres, Sexo, F. Nac) | `TA_PARIENTES`, `TA_PARENTESCOS` | Mapeo sincronizado y validación estricta de fechas. |