"""
Modelos Pydantic para el payload del webhook de BUK.

Representan la estructura real básica del JSON enviado por BUK cuando
ocurre un evento de nuevo ingreso o cambio de empleado en el webhook general.
"""

from typing import Optional
from pydantic import BaseModel


class BukWebhookMetadata(BaseModel):
    """Metadata opcional enviada en el webhook."""
    relevant_for_bukas: Optional[bool] = None
    plan_id: Optional[int] = None
    responsibility_id: Optional[int] = None


class BukWebhookData(BaseModel):
    """Estructura de la data contenida dentro del webhook de BUK."""
    employee_id: int
    date: str
    event_type: str
    tenant_url: str
    employment_status: Optional[str] = None
    metadata: Optional[BukWebhookMetadata] = None


class BukWebhookPayload(BaseModel):
    """Modelo principal que representa el payload completo enviado por el Webhook de BUK."""
    data: BukWebhookData


from datetime import date
from pydantic import Field

class FamiliarSPI(BaseModel):
    nombres_apellidos: str = Field(..., max_length=100)
    sexo: str = Field(..., max_length=1, pattern="^(M|F|m|f)$")
    fecha_nacimiento: date
    tipo_parentesco: str = Field(..., max_length=2)

class SPIEmployeePayload(BaseModel):
    """
    Representa el contrato estricto de datos requeridos por Oracle SPI.
    Todas las validaciones actúan como barrera defensiva antes del insert.
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
    
    # Atributos laborales estritos
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
