"""
Servei d'enviament de correus electrònics.
Conté la lògica d'enviar notificacions i generar el HTML de l'email.
"""
import os
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr
from datetime import datetime

logger = logging.getLogger(__name__)

# Display name configurable via .env (per defecte "Bot Cita SEPE")
_FROM_NAME = os.getenv('MAIL_FROM_NAME', 'Bot Cita SEPE')


def send_email(to_email, subject, body_html):
    """Envia un correu electrònic via SMTP SSL (Gmail)."""
    sender_email = os.getenv('MAIL_USERNAME')
    sender_password = os.getenv('MAIL_PASSWORD')
    smtp_server = "smtp.gmail.com"
    smtp_port = 465

    if not sender_email or not sender_password:
        logger.warning("No s'han configurat les credencials de correu. No s'enviarà notificació.")
        return

    try:
        msg = MIMEMultipart('alternative')
        msg['From'] = formataddr((_FROM_NAME, sender_email))
        msg['To'] = to_email
        msg['Reply-To'] = formataddr(('No Reply', sender_email))
        msg['Subject'] = subject
        msg.attach(MIMEText(body_html, 'html', 'utf-8'))

        with smtplib.SMTP_SSL(smtp_server, smtp_port) as server:
            server.login(sender_email, sender_password)
            server.send_message(msg)

        logger.info(f"Correu enviat correctament a {to_email}")
    except Exception as e:
        logger.error(f"Error enviant correu: {e}")


def build_appointment_email(dni, success_zip, type_name, types_str, scope_name, offices_info, freq_type='once'):
    """Genera un email HTML estilitzat similar a la pàgina de resultats del SEPE."""
    now_str = datetime.now().strftime('%d/%m/%Y %H:%M')
    sepe_url = 'https://sede.sepe.gob.es/portalSede/procedimientos-y-servicios/personas/proteccion-por-desempleo/cita-previa/cita-previa-solicitud.html'

    # Construir llista d'oficines
    offices_html = ''
    if offices_info:
        rows = []
        for i, office in enumerate(offices_info):
            if isinstance(office, dict):
                name = office.get('name', f'Oficina {i+1}')
                date = office.get('date', '')
            else:
                name = str(office)
                date = ''
            letter = chr(65 + i) if i < 26 else str(i + 1)
            date_html = f'<div style="background:#e8f5e9;border-left:3px solid #2e7d32;padding:6px 10px;margin-top:4px;font-size:13px;color:#1b5e20;border-radius:3px;">Primer buit disponible:<br><strong>{date}</strong></div>' if date else ''
            rows.append(f'''
            <div style="padding:12px 14px;border-bottom:1px solid #e0e0e0;">
                <table cellpadding="0" cellspacing="0" border="0"><tr>
                    <td style="vertical-align:top;padding-right:10px;"><div style="background:#00796b;color:white;width:28px;height:28px;border-radius:50%;text-align:center;line-height:28px;font-weight:bold;font-size:13px;">{letter}</div></td>
                    <td style="vertical-align:top;">
                        <div style="font-weight:600;color:#263238;font-size:14px;">{name}</div>
                        {date_html}
                    </td>
                </tr></table>
            </div>''')
        offices_html = f'''
        <div style="margin-top:20px;">
            <div style="background:#00796b;color:white;padding:10px 14px;font-weight:600;font-size:14px;border-radius:6px 6px 0 0;">Oficines disponibles</div>
            <div style="border:1px solid #e0e0e0;border-top:none;border-radius:0 0 6px 6px;background:white;">
                {''.join(rows)}
            </div>
        </div>'''

    return f'''
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#f5f5f5;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
<div style="max-width:560px;margin:20px auto;background:white;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.1);">

    <!-- Header -->
    <div style="background:#00796b;padding:24px 20px;text-align:center;">
        <div style="font-size:28px;margin-bottom:6px;">&#9989;</div>
        <div style="color:white;font-size:22px;font-weight:700;letter-spacing:0.5px;">Cita Disponible!</div>
        <div style="color:#b2dfdb;font-size:13px;margin-top:4px;">{now_str}</div>
    </div>

    <!-- Info -->
    <div style="padding:20px;">
        <table style="width:100%;border-collapse:collapse;font-size:14px;color:#37474f;">
            <tr>
                <td style="padding:8px 0;color:#78909c;width:130px;">DNI</td>
                <td style="padding:8px 0;font-weight:600;">{dni}</td>
            </tr>
            <tr>
                <td style="padding:8px 0;color:#78909c;">Codi Postal</td>
                <td style="padding:8px 0;font-weight:600;">{success_zip}</td>
            </tr>
            <tr>
                <td style="padding:8px 0;color:#78909c;">Tipus trobat</td>
                <td style="padding:8px 0;"><span style="background:#e8f5e9;color:#2e7d32;padding:2px 10px;border-radius:12px;font-weight:600;font-size:13px;">{type_name}</span></td>
            </tr>
            <tr>
                <td style="padding:8px 0;color:#78909c;">Zona</td>
                <td style="padding:8px 0;">{scope_name}</td>
            </tr>
        </table>

        {offices_html}

        <!-- CTA Button -->
        <div style="text-align:center;margin-top:24px;">
            <a href="{sepe_url}" style="display:inline-block;background:#d32f2f;color:white;text-decoration:none;padding:14px 32px;border-radius:6px;font-weight:700;font-size:15px;letter-spacing:0.3px;">Reservar cita ara &rarr;</a>
        </div>
        <p style="text-align:center;color:#90a4ae;font-size:12px;margin-top:12px;">El bot <strong>no</strong> reserva automàticament. Ves a la web del SEPE per completar la reserva.</p>
        {'<div style="margin-top:18px;background:#fff3e0;border:1px solid #ffe0b2;border-left:4px solid #f57c00;border-radius:6px;padding:12px 16px;"><div style="font-weight:600;color:#e65100;font-size:13px;margin-bottom:4px;">⚠️ Recomanació: Cancel·la la cerca recurrent</div><div style="color:#5d4037;font-size:12px;">Si ja has reservat la cita, recorda <strong>esborrar la cerca activa</strong> a la pàgina del bot. Així alliberaràs recursos del servidor perquè altres persones puguin fer servir el servei. Gràcies!</div></div>' if freq_type != 'once' else ''}
    </div>

    <!-- Footer -->
    <div style="background:#fafafa;padding:14px 20px;text-align:center;border-top:1px solid #e0e0e0;">
        <span style="color:#b0bec5;font-size:12px;">Bot Cita SEPE &mdash; <a href="https://frolesti.aixeta.cat/ca" style="color:#00796b;text-decoration:none;">frolesti.aixeta.cat</a></span>
    </div>
</div>
</body>
</html>'''
