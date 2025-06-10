import random
import smtplib
import logging
import os
from datetime import datetime, date
import requests
from dotenv import load_dotenv
import urllib3

from time import sleep
from email.message import EmailMessage
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

# Disable only the single InsecureRequestWarning from urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Load environment variables from .env file
load_dotenv()

# Now you can access the variables using os.getenv
clock_in_active = os.getenv('CLOCK_IN_ACTIVE')
debug_mode = os.getenv('DEBUG_MODE')
email_address = os.getenv('EMAIL_ADDRESS')
email_pass = os.getenv('EMAIL_PASS')

# VARIABLES DE ENTORNO Y VALIDACIONES INICIALES
DEBUG_MODE = debug_mode.lower() == "true"
CLOCK_IN_ACTIVE = clock_in_active.lower() == "true"
EMAIL = email_address
EMAIL_PASS = email_pass

# CONFIGURACIÓN DE LOGS
logging.basicConfig(
    filename="marcaje.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

# Validar variables de entorno requeridas
if not EMAIL or not EMAIL_PASS:
    logging.error(
        "Las variables de entorno EMAIL_ADDRESS y EMAIL_PASS son requeridas")
    exit(1)

# CONFIGURACIÓN DEL CORREO
EMAIL_FROM = EMAIL
EMAIL_TO = EMAIL
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587

# COORDENADAS POR UBICACIÓN
LOCATIONS = {
    "HomeWork": {"latitude": "-33.4147", "longitude": "-70.5983"},
    "PresentialWork": {"latitude": "-33.5169", "longitude": "-70.7571"}
}

# Función para obtener ubicación según día


def get_location_for_day():
    day = datetime.now().weekday()
    if day in [0, 3]:  # Lunes y Jueves
        return LOCATIONS["HomeWork"]
    elif day in [1, 2, 4]:  # Martes, Miércoles y Viernes
        return LOCATIONS["PresentialWork"]
    return None

# Función para verificar si es feriado


def is_holiday():
    try:
        headers = {
            'accept': 'application/json'
        }
        response = requests.get(
            'https://api.boostr.cl/holidays.json', headers=headers)

        if response.status_code == 200:
            result = response.json()
            if result['status'] == 'success':
                today = date.today().strftime("%Y-%m-%d")
                holidays = result['data']

                # Check if today is a holiday
                holiday = next(
                    (h for h in holidays if h['date'] == today), None)
                if holiday:
                    logging.info(
                        f"Hoy es feriado: {holiday['title']} ({holiday['type']})")

                    # Send holiday email notification with emoji
                    email = EmailMessage()
                    email["From"] = EMAIL_FROM
                    email["To"] = EMAIL_TO
                    email["Subject"] = f"🎉 Feriado: {holiday['title']} - No hay marcaje"
                    email.set_content(
                        f"Hoy es feriado ({holiday['title']}), no se realizará marcaje.\nTipo: {holiday['type']}\nExtra: {holiday['extra']}")

                    try:
                        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as smtp:
                            smtp.starttls()
                            smtp.login(EMAIL_FROM, EMAIL_PASS)
                            smtp.send_message(email)
                        logging.info("Correo de feriado enviado.")
                    except Exception as mail_error:
                        logging.error(
                            f"No se pudo enviar correo de feriado: {str(mail_error)}")

                    return True

        else:
            logging.warning(
                f"API de feriados retornó status code: {response.status_code}")

    except requests.exceptions.RequestException as e:
        logging.warning(f"No se pudo verificar feriados: {str(e)}")

    return False


def main():
    # RETARDO ALEATORIO DE 1 A 20 MINUTOS (1 MINUTO EN DEBUG)
    delay_min = 1 if DEBUG_MODE else random.randint(1, 20)
    logging.info(f"Esperando {delay_min} minutos antes de ejecutar el script.")
    print(f"⏳ Esperando {delay_min} minutos antes de iniciar marcaje...")
    sleep(delay_min * 60)

    # MARCAJE AUTOMÁTICO SOLO SI debug ES FALSO
    try:
        # OBTENER HORA UTC Y CONVERTIR A CHILE
        utc_now = datetime.utcnow()
        # Chile está UTC-3 (la mayor parte del año) o UTC-4 (invierno)
        # Ajustamos -4 horas para ser conservadores
        chile_hour = (utc_now.hour - 4) % 24

        # Para logging y mensajes, calculamos la hora completa de Chile
        chile_time = datetime(utc_now.year, utc_now.month,
                              utc_now.day, chile_hour, utc_now.minute, utc_now.second)

        action_type = "ENTRADA" if chile_hour < 12 else "SALIDA"

        print(f"🕐 Hora UTC: {utc_now.strftime('%H:%M:%S')}")
        print(f"🇨🇱 Hora Chile (estimada): {chile_time.strftime('%H:%M:%S')}")
        print(f"📍 Tipo de marcaje: {action_type}")

        # Add this line after getting chile_time
        current_location = "HOME" if get_location_for_day(
        ) == LOCATIONS["HomeWork"] else "WORK"

        if not DEBUG_MODE:
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

            mensaje = f"✅ {action_type} realizada con éxito a las {chile_time.strftime('%H:%M:%S')} (Chile)."
            logging.info(mensaje)
        else:
            mensaje = f"🧪 DEBUG activo: no se ejecutó marcaje. Hora Chile: {chile_time.strftime('%H:%M:%S')}"
            logging.info(mensaje)

        # Enviar correo de confirmación
        print("📨 Enviando correo de confirmación...")
        email = EmailMessage()
        email["From"] = EMAIL_FROM
        email["To"] = EMAIL_TO
        # Modify the email subject line
        email["Subject"] = f"{action_type} ({current_location}) {'(simulada)' if DEBUG_MODE else ''} completada"
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

        # Update the error email subject too
        email = EmailMessage()
        email["From"] = EMAIL_FROM
        email["To"] = EMAIL_TO
        email["Subject"] = f"Error en {action_type} ({current_location})"
        email.set_content(error_msg)

        # Enviar correo de error
        try:
            with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as smtp:
                smtp.starttls()
                smtp.login(EMAIL_FROM, EMAIL_PASS)
                smtp.send_message(email)
            logging.info("Correo de error enviado.")
        except Exception as mail_error:
            logging.error(
                f"No se pudo enviar correo de error: {str(mail_error)}")

    finally:
        if not DEBUG_MODE and 'driver' in locals():
            driver.quit()
            logging.info("Navegador cerrado.")


# Verificar si debemos ejecutar el script
if __name__ == "__main__":
    if not CLOCK_IN_ACTIVE:
        logging.info(
            "Script desactivado por variable de entorno CLOCK_IN_ACTIVE")
        exit()

    if is_holiday():
        logging.info("Hoy es feriado, no se ejecutará el marcaje")
        exit()

    main()
