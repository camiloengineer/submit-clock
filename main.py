import random
import smtplib
import logging
from time import sleep
from datetime import datetime
from email.message import EmailMessage
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

# MODO DEBUG
debug = True  # Cambiar a True para desactivar la marcación y solo hacer pruebas de notificación

# CONFIGURACIÓN DEL CORREO
EMAIL_FROM = "camilo@camiloengineer.com"
EMAIL_TO = "camilo@camiloengineer.com"
EMAIL_PASS = "mbgq asiy vfaa wdit"
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587

# CONFIGURACIÓN DE LOGS
logging.basicConfig(
    filename="marcaje.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

# RETARDO ALEATORIO DE 1 A 20 MINUTOS
delay_min = random.randint(1, 2)
logging.info(f"Esperando {delay_min} minutos antes de ejecutar el script.")
print(f"⏳ Esperando {delay_min} minutos antes de iniciar marcaje...")
sleep(delay_min * 60)

# MARCAJE AUTOMÁTICO SOLO SI debug ES FALSO
try:
    now = datetime.now()
    current_hour = now.hour
    action_type = "ENTRADA" if current_hour < 12 else "SALIDA"

    if not debug:
        logging.info("Iniciando navegador en modo headless.")
        options = Options()
        options.add_argument("--headless")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")

        driver = webdriver.Chrome(options=options)
        logging.info("Cargando página de marcaje...")
        driver.get("https://app.ctrlit.cl/ctrl/dial/web/K1NBpBqyjf")
        driver.implicitly_wait(10)
        sleep(2)

        logging.info(f"Tipo de marcaje: {action_type}")
        print(f"🔍 Buscando botón {action_type}...")
        boton = next((el for el in driver.find_elements(By.CSS_SELECTOR, 'button, div, span, li')
                     if el.text.strip().upper() == action_type), None)
        if not boton:
            raise Exception(f"❌ No se encontró botón {action_type}")
        boton.click()
        sleep(2)

        print("🔢 Ingresando RUT...")
        rut = "16913376K"
        for char in rut:
            found = False
            for el in driver.find_elements(By.CSS_SELECTOR, "li.digits"):
                if el.text.strip().upper() == char:
                    el.click()
                    found = True
                    logging.info(f"Click en {char}")
                    break
            if not found:
                raise Exception(f"❌ No se encontró el carácter: {char}")
            sleep(0.3)

        sleep(1)

        print("📤 Haciendo click en ENVIAR...")
        enviar = next((el for el in driver.find_elements(By.CSS_SELECTOR, 'li.pad-action.digits')
                      if el.text.strip().upper() == "ENVIAR"), None)
        if not enviar:
            raise Exception("❌ No se encontró botón ENVIAR")
        enviar.click()
        sleep(1)

        mensaje = f"✅ {action_type} realizada con éxito a las {now.strftime('%H:%M:%S')}."
        logging.info(mensaje)
    else:
        mensaje = f"🧪 DEBUG activo: no se ejecutó marcaje. Hora simulada: {now.strftime('%H:%M:%S')}"
        logging.info(mensaje)

    # Enviar correo de confirmación
    print("📨 Enviando correo de confirmación...")
    email = EmailMessage()
    email["From"] = EMAIL_FROM
    email["To"] = EMAIL_TO
    email["Subject"] = f"{action_type} {'(simulada)' if debug else ''} completada"
    email.set_content(mensaje)

    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as smtp:
        smtp.starttls()
        smtp.login(EMAIL_FROM, EMAIL_PASS)
        smtp.send_message(email)
    logging.info("Correo enviado con éxito.")

except Exception as e:
    error_msg = f"❌ Error en marcaje: {str(e)}"
    print(error_msg)
    logging.error(error_msg)

    # Enviar correo de error
    email = EmailMessage()
    email["From"] = EMAIL_FROM
    email["To"] = EMAIL_TO
    email["Subject"] = f"Error en {action_type}"
    email.set_content(error_msg)

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as smtp:
            smtp.starttls()
            smtp.login(EMAIL_FROM, EMAIL_PASS)
            smtp.send_message(email)
        logging.info("Correo de error enviado.")
    except Exception as mail_error:
        logging.error(f"No se pudo enviar correo de error: {str(mail_error)}")

finally:
    if not debug and 'driver' in locals():
        driver.quit()
        logging.info("Navegador cerrado.")
