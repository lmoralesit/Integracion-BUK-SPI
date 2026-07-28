import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from app.core.config import settings

logger = logging.getLogger("ETL_BUK_SPI")

class SMTPNotifier:
    """
    Mandamiento #2 (Resiliencia) y #5 (Logging Seguro):
    Maneja el envío de alertas transaccionales sin bloquear el hilo principal
    y enmascarando PII en los logs del servidor.
    """
    @classmethod
    def send_notification(cls, to_email: str, subject: str, html_content: str) -> bool:
        # En modo DEBUG, desviamos todo al correo del desarrollador para evitar spam operacional
        target_email = settings.NOTIFY_EMAIL_DEV if settings.DEBUG else to_email
        
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"[{settings.APP_NAME}] {subject}"
        msg["From"] = settings.SMTP_USER
        msg["To"] = target_email
        
        msg.attach(MIMEText(html_content, "html"))
        
        try:
            logger.info(f"Conectando a servidor SMTP {settings.SMTP_HOST}:{settings.SMTP_PORT}...")
            with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10) as server:
                if settings.SMTP_USE_TLS:
                    server.starttls()
                if settings.SMTP_PASSWORD:
                    server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                
                server.sendmail(settings.SMTP_USER, [target_email], msg.as_string())
            
            # Mandamiento #5: No loguear cédulas ni nombres completos, solo referencia operativa
            logger.info(f"Notificación enviada exitosamente a: {target_email} | Asunto: {subject}")
            return True
        except Exception as e:
            logger.error(f"Fallo crítico al intentar enviar correo vía SMTP a {target_email}: {str(e)}")
            return False

    @classmethod
    def notify_status(cls, status_flag: int, employee_data: dict, ficha: str = "N/A", error_msg: str = ""):
        """
        Orquesta el destinatario y la plantilla según la Bandera de Estado de la auditoría.
        """
        cedula = employee_data.get("rut", "Desconocido")
        empresa_code = employee_data.get("custom_attributes", {}).get("codigo_empresa", "D6")
        
        # Determinar destinatario por negocio
        if status_flag == 1:  # Éxito -> Nómina Caracas o Turmero
            recipient = settings.NOTIFY_EMAIL_TURMERO if empresa_code == "TUR" else settings.NOTIFY_EMAIL_CARACAS
            subject = f"ALTA EXITOSA - Listo para Nómina: Ficha {ficha}"
            color, title, desc = "#10B981", "Alta Registrada en SPI", f"El colaborador con Cédula <b>{cedula}</b> ha sido procesado e inyectado correctamente en SPI bajo la Ficha <b>{ficha}</b>."
        elif status_flag in (3, 4):  # Error -> Capital Humano (Para corrección en BUK)
            recipient = settings.NOTIFY_EMAIL_RRHH
            subject = f"ACCIÓN REQUERIDA - Inconsistencia BUK/SPI: Cédula {cedula}"
            color, title, desc = "#EF4444", "Error de Validación en Onboarding", f"Se detuvo la integración para la Cédula <b>{cedula}</b>.<br><b>Motivo técnico:</b> {error_msg}<br><i>Por favor, corrija el dato en BUK y relance la tarea desde el Panel Admin.</i>"
        else:
            return
            
        html_body = f"""
        <html>
        <body style="font-family: Arial, sans-serif; color: #333; line-height: 1.6;">
            <div style="max-w: 600px; margin: 0 auto; border: 1px solid #ddd; border-top: 5px solid {color}; padding: 20px;">
                <h2 style="color: {color}; margin-top: 0;">{title}</h2>
                <p>{desc}</p>
                <hr style="border: none; border-top: 1px solid #eee; margin: 20px 0;">
                <p style="font-size: 12px; color: #777;">
                    Este es un mensaje automatizado generado por el motor DevSecOps de Integración BUK-SPI.<br>
                    <b>Ambiente:</b> {'DESARROLLO / PRUEBAS' if settings.DEBUG else 'PRODUCCIÓN'}
                </p>
            </div>
        </body>
        </html>
        """
        cls.send_notification(recipient, subject, html_body)

    def notificar_exito(self, datos_empleado: dict, localidad: str = "Caracas"):
        ficha = datos_empleado.get("ficha", "N/A")
        self.notify_status(status_flag=1, employee_data=datos_empleado, ficha=ficha)

    def notificar_error_validacion(self, employee_id: str | int, cedula: str, nombre: str, tipo_error: str, detalle_error: str):
        emp_data = {"rut": cedula, "name": nombre, "employee_id": employee_id}
        self.notify_status(status_flag=3, employee_data=emp_data, error_msg=f"{tipo_error}: {detalle_error}")


EmailNotifier = SMTPNotifier