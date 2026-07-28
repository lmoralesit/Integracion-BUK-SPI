"""
Funciones de Transformación y Sanitización – ETL BUK → SPI.

Código funcional que implementa las Reglas de Negocio del contexto
del proyecto (Sección 3). Cada función recibe datos crudos de BUK,
los sanitiza asegurando que sean cadenas, y retorna el valor limpio.
"""

import re
import unicodedata
from typing import Optional, Any, Dict


# ──────────────────────────────────────────────
# 1. Truncar el .0 de los códigos de cargo
# ──────────────────────────────────────────────


def truncar_codigo_cargo(codigo_cargo: Any) -> str:
    """
    Elimina el sufijo '.0' que BUK agrega a los códigos de cargo
    y aplica slicing a 36 caracteres (límite del campo Puesto en SPI).
    Conversión segura a string incorporada.
    """
    if codigo_cargo is None:
        return ""

    valor_str = str(codigo_cargo).strip()
    if not valor_str:
        return ""

    limpio = re.sub(r"\.0+$", "", valor_str)
    return limpio[:36]


# ──────────────────────────────────────────────
# 2. Limpiar y formatear el RIF y Cédula
# ──────────────────────────────────────────────


def limpiar_cedula(cedula: Any) -> str:
    """
    Limpia la cédula removiendo puntos, guiones y espacios.
    Ejemplo: '27.359.015' -> '27359015'
    """
    if cedula is None:
        return ""
    
    valor_str = str(cedula).strip()
    return valor_str.replace(".", "").replace("-", "").replace(" ", "")


def formatear_rif(tipo_rif: Any, numero_rif: Any) -> str:
    """
    Tarea 3.1: Limpia guiones y puntos del RIF, antepone la letra en mayúscula.
    Asegura formato tipo 'V145758120' sin separadores ni duplicados.
    """
    if tipo_rif is None and numero_rif is None:
        return ""

    tipo = str(tipo_rif).strip().upper() if tipo_rif is not None else ""
    numero = str(numero_rif).strip().upper() if numero_rif is not None else ""
    
    # Limpiar todos los separadores
    numero = numero.replace("-", "").replace(".", "").replace(" ", "")

    # Si la letra inicial ya viene dentro de numero (ej: 'V145758120')
    if numero and numero[0] in ("V", "E", "J", "G", "P", "C"):
        if not tipo:
            tipo = numero[0]
            numero = numero[1:]
        elif tipo == numero[0]:
            numero = numero[1:]

    return f"{tipo}{numero}"


# ──────────────────────────────────────────────
# 3. Sanitizar nombres (quitar acentos)
# ──────────────────────────────────────────────


def sanitizar_nombre(nombre: Any) -> str:
    """
    Tarea 3.1: Remueve acentos de nombres para compatibilidad ASCII con SPI.
    Resultado final en mayúsculas sin caracteres especiales críticos.
    """
    if nombre is None:
        return ""

    valor_str = str(nombre).strip()
    if not valor_str:
        return ""

    sin_acentos = (
        unicodedata.normalize("NFD", valor_str)
        .encode("ascii", "ignore")
        .decode("utf-8")
    )

    # Eliminar cualquier caracter que no sea alfanumérico o espacio
    limpio = re.sub(r"[^A-Za-z0-9\s]", "", sin_acentos)
    return limpio.upper().strip()


# ──────────────────────────────────────────────
# 4. Manejar valores nulos en contacto
# ──────────────────────────────────────────────


def valor_neutro_contacto(valor: Any, caracter_neutro: str = ".") -> str:
    """
    Tarea 3.3: Si teléfono o correo viene vacío/None, inserta '.' o '-'.
    """
    if valor is None:
        return caracter_neutro

    valor_str = str(valor).strip()
    if valor_str:
        return valor_str

    return caracter_neutro


# ──────────────────────────────────────────────
# 5. Truncar nombre de puesto (máx 36 chars)
# ──────────────────────────────────────────────


def truncar_puesto(nombre_puesto: Any, max_length: int = 36) -> str:
    """
    Tarea 3.2: Trunca el nombre del puesto al límite de 36 caracteres de SPI.
    """
    if nombre_puesto is None:
        return ""

    valor_str = str(nombre_puesto).strip()
    return valor_str[:max_length]


# ──────────────────────────────────────────────
# 6. Herencia de Lugar de Nacimiento (Tarea 3.3)
# ──────────────────────────────────────────────


def heredar_lugar_nacimiento(
    pais_residencia: Any,
    entidad_residencia: Any,
    municipio_residencia: Any
) -> Dict[str, str]:
    """
    Tarea 3.3: Al carecer BUK del campo Lugar de Nacimiento, hereda el País,
    Entidad Federal (Estado) y Municipio desde la dirección de residencia actual.
    """
    pais = str(pais_residencia).strip() if pais_residencia else "VENEZUELA"
    entidad = str(entidad_residencia).strip() if entidad_residencia else "."
    municipio = str(municipio_residencia).strip() if municipio_residencia else "."

    return {
        "pais_nacimiento": sanitizar_nombre(pais) or "VENEZUELA",
        "entidad_nacimiento": sanitizar_nombre(entidad) or ".",
        "municipio_nacimiento": sanitizar_nombre(municipio) or ".",
    }

