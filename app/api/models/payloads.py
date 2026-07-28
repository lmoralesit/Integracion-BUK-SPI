"""
Modelos Pydantic para validación estricta de payloads de entrada (app.api.models.payloads).
Incluye los esquemas del Webhook BUK y el contrato de datos requerido por Oracle SPI.
"""

from datetime import date
from typing import Optional
from pydantic import BaseModel, Field, field_validator


# ──────────────────────────────────────────────
# Esquema de Entrada: Webhook BUK (Event-Driven)
# ──────────────────────────────────────────────
class BukWebhookPayload(BaseModel):
    """Payload tipado y sanitizado del Webhook de BUK Cloud."""
    employee_id: int = Field(..., description="ID único del colaborador en BUK", gt=0)
    event_type: str = Field(..., description="Tipo de evento disparado por el workflow")

    @field_validator("event_type")
    @classmethod
    def validate_event_type(cls, v: str) -> str:
        allowed_events = {"employee_create", "employee_update", "solicitud_ingreso", "job_hire"}
        clean_v = v.lower().strip()
        if clean_v not in allowed_events:
            raise ValueError(f"Evento no autorizado o no reconocido: {clean_v}")
        return clean_v


# ──────────────────────────────────────────────
# Esquema de Carga Familiar SPI
# ──────────────────────────────────────────────
class FamiliarSPI(BaseModel):
    nombres_apellidos: str = Field(..., max_length=100)
    sexo: str = Field(..., max_length=1, pattern="^(M|F|m|f)$")
    fecha_nacimiento: date
    tipo_parentesco: str = Field(..., max_length=2)


# ──────────────────────────────────────────────
# Esquema de Salida: Contrato Estricto Oracle SPI
# ──────────────────────────────────────────────
class SPIEmployeePayload(BaseModel):
    """
    Representa el contrato estricto de datos requeridos por Oracle SPI.
    Todas las validaciones actúan como barrera defensiva antes del INSERT.
    """
    cedula: str = Field(..., max_length=20, description="Cédula única del empleado")
    primer_nombre: str = Field(..., max_length=50)
    segundo_nombre: Optional[str] = Field("", max_length=50)
    primer_apellido: str = Field(..., max_length=50)
    segundo_apellido: Optional[str] = Field("", max_length=50)

    # Sexo debe ser M o F, cualquier otra cosa es rechazada.
    sexo: str = Field(..., max_length=1, pattern="^(M|F|m|f)$")

    fecha_nacimiento: date
    nacionalidad: str = Field(..., max_length=50)
    estado_civil: str = Field(..., max_length=2)
    rif: str = Field(..., max_length=20)

    telefono_celular: Optional[str] = Field(None, max_length=20)
    correo_personal: Optional[str] = Field(None, max_length=100)

    # Atributos laborales estrictos
    codigo_cargo: str = Field(..., max_length=10)
    nombre_cargo: str = Field(..., max_length=100)
    centro_costo: str = Field(..., max_length=20)
    unidad_organizativa: str = Field(..., max_length=100)
    codigo_empresa: str = Field(..., max_length=10)
    fecha_inicio: date
    ficha: str = Field(..., max_length=20)
    localidad: str = Field(..., max_length=10)

    # Familiares
    cargas_familiares: list[FamiliarSPI] = Field(default_factory=list)

    class Config:
        from_attributes = True
