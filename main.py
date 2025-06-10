import random
import smtplib
import logging
import os
from datetime import datetime, date
import requests
from dotenv import load_dotenv
import urllib3
import ldclient
from ldclient import Context
from ldclient.config import Config

from time import sleep
from email.message import EmailMessage
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut
import googlemaps

# Disable only the single InsecureRequestWarning from urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Create logs directory if it doesn't exist
logs_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
os.makedirs(logs_dir, exist_ok=True)

# Generate log filename with pattern
current_date = datetime.now().strftime('%Y-%m-%d')

# If in GitHub Actions use run number, otherwise use '*'
log_filename = f"marcaje-logs-{os.getenv('GITHUB_RUN_NUMBER', '*')}-{current_date}.log"
log_filepath = os.path.join(logs_dir, log_filename)

# CONFIGURACIÓN DE LOGS
logging.basicConfig(
    filename=log_filepath,
    level=logging.INFO,
    format="%(asctime)s-%(levelname)s-%(message)s",  # Removed spaces
    force=True
)

logging.info(f"Iniciando logging en archivo: {log_filepath}")

# Load environment variables from .env file
load_dotenv()

# Get LaunchDarkly SDK key from environment
ld_sdk_key = os.getenv('LAUNCHDARKLY_SDK_KEY')
if not ld_sdk_key:
    logging.error("LAUNCHDARKLY_SDK_KEY no está configurada")
    exit(1)

# Debug logging for SDK key
logging.info("=== Iniciando configuración de LaunchDarkly ===")
logging.info(
    f"SDK Key encontrada (primeros 8 caracteres): {ld_sdk_key[:8]}...")
logging.info(f"Longitud de SDK Key: {len(ld_sdk_key)}")

# Remove quotes and whitespace if present
ld_sdk_key = ld_sdk_key.strip().strip("'").strip('"')
logging.info(
    f"SDK Key después de limpieza (primeros 8 caracteres): {ld_sdk_key[:8]}...")

# Initialize LaunchDarkly client
try:
    # Configuración básica
    config = Config(
        sdk_key=ld_sdk_key,
        stream_uri="https://stream.launchdarkly.com",
        base_uri="https://app.launchdarkly.com",
        events_uri="https://events.launchdarkly.com",
        offline=False
    )

    # Inicializar cliente
    ldclient.set_config(config)

    # Verificar inicialización
    if ldclient.get().is_initialized():
        logging.info("✅ LaunchDarkly client inicializado correctamente")
    else:
        logging.error("❌ LaunchDarkly client no se inicializó correctamente")
        exit(1)

except Exception as e:
    logging.error(f"❌ Error al inicializar LaunchDarkly: {str(e)}")
    exit(1)

# Now you can access the variables using os.getenv
clock_in_active = os.getenv('CLOCK_IN_ACTIVE')
debug_mode = os.getenv('DEBUG_MODE')
email_address = os.getenv('EMAIL_ADDRESS')
email_pass = os.getenv('EMAIL_PASS')

# VARIABLES DE ENTORNO Y VALIDACIONES INICIALES
DEBUG_MODE = debug_mode.lower() == "true" if debug_mode else False
CLOCK_IN_ACTIVE = clock_in_active.lower() == "true" if clock_in_active else False
EMAIL = email_address
EMAIL_PASS = email_pass

# CONFIGURACIÓN DEL CORREO
EMAIL_FROM = EMAIL
EMAIL_TO = EMAIL
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587

# CÓDIGOS POSTALES POR UBICACIÓN
LOCATIONS = {
    "HomeWork": {"postal_code": "9250000"},  # Maipú
    "PresentialWork": {"postal_code": "7550000"}  # Las Condes
}

CHILE_HOLIDAYS_2025 = [
    {"date": "2025-01-01", "title": "Año Nuevo", "type": "Civil"},
    {"date": "2025-04-18", "title": "Viernes Santo", "type": "Religioso"},
    {"date": "2025-04-19", "title": "Sábado Santo", "type": "Religioso"},
    {"date": "2025-05-01", "title": "Día Nacional del Trabajo", "type": "Civil"},
    {"date": "2025-05-21", "title": "Día de las Glorias Navales", "type": "Civil"},
    {"date": "2025-06-29", "title": "San Pedro y San Pablo", "type": "Religioso"},
    {"date": "2025-07-16", "title": "Día de la Virgen del Carmen", "type": "Religioso"},
    {"date": "2025-08-15", "title": "Asunción de la Virgen", "type": "Religioso"},
    {"date": "2025-09-18", "title": "Independencia Nacional", "type": "Civil"},
    {"date": "2025-09-19", "title": "Día de las Glorias del Ejército", "type": "Civil"},
    {"date": "2025-12-08", "title": "Inmaculada Concepción", "type": "Religioso"},
    {"date": "2025-12-25", "title": "Navidad", "type": "Religioso"}
]


def get_location_info(postal_code: str) -> dict:
    """Get location coordinates and comuna from postal code using Google Maps API"""
    try:
        gmaps = googlemaps.Client(key=os.getenv('GOOGLE_MAPS_API_KEY'))

        # Search with postal code and city for better results
        query = f"{postal_code}, Santiago, Chile"
        result = gmaps.geocode(query, region='cl')

        if result:
            location = result[0]

            # Extract comuna from address components
            comuna = None
            for component in location['address_components']:
                if 'sublocality' in component['types']:
                    comuna = component['long_name']
                    break

            # Normalize comuna names
            if comuna:
                if comuna.lower() == 'maipu':
                    comuna = 'Maipú'
                elif comuna.lower() == 'las condes':
                    comuna = 'Las Condes'

            # If no comuna found, use known values
            if not comuna:
                comuna = 'Maipú' if postal_code == '9250000' else 'Las Condes'

            coordinates = location['geometry']['location']

            logging.info(
                f"Ubicación encontrada para código postal {postal_code}")
            logging.info(f"Comuna identificada: {comuna}")
            logging.info(
                f"Coordenadas: {coordinates['lat']}, {coordinates['lng']}")

            return {
                "latitude": str(coordinates['lat']),
                "longitude": str(coordinates['lng']),
                "comuna": comuna
            }

        logging.error(
            f"No se encontró ubicación para código postal: {postal_code}")
        return None

    except Exception as e:
        logging.error(f"Error al obtener ubicación: {str(e)}")
        return None


def get_location_for_day():
    day = datetime.now().weekday()
    # Fix: Changed the logic to match the correct days
    location_type = "PresentialWork" if day in [
        0, 3] else "HomeWork" if day in [1, 2, 4] else None

    if not location_type:
        return None

    postal_code = LOCATIONS[location_type]["postal_code"]
    location_info = get_location_info(postal_code)

    if location_info:
        logging.info(
            f"Ubicación encontrada para {location_type}: {location_info['comuna']}")
        return location_info
    return None


def is_holiday():
    try:
        headers = {'accept': 'application/json'}
        response = requests.get(
            'https://api.boostr.cl/holidays.json', headers=headers, timeout=5)

        if response.status_code == 200:
            result = response.json()
            if result['status'] == 'success':
                holidays = result['data']
                today = date.today().strftime("%Y-%m-%d")

                holiday = next(
                    (h for h in holidays if h['date'] == today), None)
                if holiday:
                    logging.info(
                        f"Hoy es feriado (API): {holiday['title']} ({holiday['type']})")
                    send_holiday_email(holiday, "API")
                    return True
            else:
                raise Exception(
                    f"API retornó estado no exitoso: {result['status']}")
        else:
            raise Exception(f"API retornó status code: {response.status_code}")

    except Exception as e:
        logging.warning(f"API de feriados no disponible: {str(e)}")
        logging.info("Utilizando lista de feriados local...")

        today = date.today().strftime("%Y-%m-%d")
        holiday = next(
            (h for h in CHILE_HOLIDAYS_2025 if h['date'] == today), None)

        if holiday:
            logging.info(
                f"Hoy es feriado (LOCAL): {holiday['title']} ({holiday['type']})")
            send_holiday_email(holiday, "LOCAL")
            return True

    return False


def send_holiday_email(holiday, source):
    try:
        email = EmailMessage()
        email["From"] = EMAIL_FROM
        email["To"] = EMAIL_TO
        email["Subject"] = f"🎉 Feriado: {holiday['title']} - No hay marcaje"

        content = f"""Hoy es feriado ({holiday['title']}), no se realizará marcaje.
Tipo: {holiday['type']}
Fuente: {'API en línea' if source == 'API' else 'Lista local (API no disponible)'}"""

        email.set_content(content)

        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as smtp:
            smtp.starttls()
            smtp.login(EMAIL_FROM, EMAIL_PASS)
            smtp.send_message(email)
        logging.info(f"Correo de feriado enviado (fuente: {source})")
    except Exception as mail_error:
        logging.error(
            f"No se pudo enviar correo de feriado: {str(mail_error)}")


def is_valid_rut(rut):
    """Valida que el flag key tenga formato de RUT chileno (sin puntos ni guiones)."""
    try:
        rut = rut.lower()

        # Verificar longitud (7-8 dígitos + dígito verificador)
        if not (8 <= len(rut) <= 9):
            return False

        # Verificar que termina en número o 'k'
        if not rut[-1].isdigit() and rut[-1] != 'k':
            return False

        # Verificar que el resto son números
        if not rut[:-1].isdigit():
            return False

        return True
    except:
        return False


def is_clock_in_active():
    context = Context.builder("default").name("default").build()

    try:
        all_flags = ldclient.get().all_flags_state(context)

        if all_flags.valid:
            flags_dict = all_flags.to_json_dict()
            for flag_key in flags_dict:
                # Ignorar flags del sistema y otros flags conocidos
                if flag_key.startswith('$') or flag_key == 'CLOCK_IN_ACTIVE':
                    logging.info(f"Flag del sistema encontrado: {flag_key}")
                    continue

                # Validar si es un RUT
                if is_valid_rut(flag_key):
                    status = "activo" if flags_dict[flag_key] else "desactivado"
                    logging.info(
                        f"RUT válido encontrado: {flag_key} ({status})")
                    if flags_dict[flag_key]:
                        return flag_key
                else:
                    logging.warning(f"Flag no válido como RUT: {flag_key}")

            logging.warning("No se encontraron RUTs válidos activos")
            return None

    except Exception as e:
        logging.error(f"Error al obtener flags: {str(e)}")
        return None


def process_rut(rut: str) -> None:
    """Process a single RUT in its own thread"""
    try:
        logging.info(f"🧵 Iniciando proceso para RUT: {rut}")

        # Create context for this specific RUT
        context = Context.builder(rut).name(rut).build()

        # Check if RUT is active
        if not ldclient.get().variation(rut, context, False):
            logging.warning(f"RUT {rut} está desactivado")
            return

        # Run the main logic for this RUT
        if is_holiday():
            logging.info(
                f"Hoy es feriado - no se ejecuta marcaje para RUT {rut}")
            return

        # OBTENER HORA UTC Y CONVERTIR A CHILE
        utc_now = datetime.utcnow()
        chile_hour = (utc_now.hour - 4) % 24

        chile_time = datetime(utc_now.year, utc_now.month,
                              utc_now.day, chile_hour, utc_now.minute, utc_now.second)

        action_type = "ENTRADA" if chile_hour < 12 else "SALIDA"

        location_info = get_location_for_day()
        if not location_info:
            raise Exception("No se pudo obtener información de ubicación")

        # Fix: Changed the logic to match the correct days
        current_location = "WORK" if datetime.now().weekday() in [
            0, 3] else "HOME"
        comuna = location_info.get('comuna', 'Comuna desconocida')

        print(f"🕐 Hora UTC: {utc_now.strftime('%H:%M:%S')}")
        print(f"🇨🇱 Hora Chile (estimada): {chile_time.strftime('%H:%M:%S')}")
        print(f"📍 Tipo de marcaje: {action_type} en {comuna}")  # Added comuna

        if not DEBUG_MODE:
            logging.info("Iniciando navegador en modo headless.")
            options = Options()
            options.add_argument("--headless")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--disable-gpu")
            options.add_argument("--window-size=1920,1080")

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

            # Log parcial por seguridad
            print(f"🔢 Ingresando RUT: {rut[:4]}****")
            for char in rut:
                found = False
                for el in driver.find_elements(By.CSS_SELECTOR, "li.digits"):
                    if el.text.strip().upper() == char:
                        el.click()
                        found = True
                        logging.info(f"Click en carácter de RUT")
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
        email["Subject"] = f"{action_type} ({current_location} - {comuna}) {'(simulada)' if DEBUG_MODE else ''} completada"
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

        email = EmailMessage()
        email["From"] = EMAIL_FROM
        email["To"] = EMAIL_TO
        email["Subject"] = f"Error en {action_type} ({current_location})"
        email.set_content(error_msg)

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


def get_active_ruts() -> List[str]:
    """Get all valid RUTs from LaunchDarkly flags"""
    active_ruts = []
    try:
        context = Context.builder("default").name("default").build()
        all_flags = ldclient.get().all_flags_state(context)

        if all_flags.valid:
            flags_dict = all_flags.to_json_dict()
            for flag_key in flags_dict:
                if not flag_key.startswith('$') and flag_key != 'CLOCK_IN_ACTIVE':
                    if is_valid_rut(flag_key):
                        active_ruts.append(flag_key)
                        logging.info(f"RUT válido encontrado: {flag_key}")

        return active_ruts
    except Exception as e:
        logging.error(f"Error obteniendo RUTs: {str(e)}")
        return []


# Verificar si debemos ejecutar el script
if __name__ == "__main__":
    if not CLOCK_IN_ACTIVE:
        logging.info(
            "Script desactivado por variable de entorno CLOCK_IN_ACTIVE")
        exit()

    if is_holiday():
        logging.info("Hoy es feriado, no se ejecutará el marcaje")
        exit()

    ruts = get_active_ruts()
    if not ruts:
        logging.warning("No se encontraron RUTs válidos")
    else:
        logging.info(f"Procesando {len(ruts)} RUTs en paralelo")

        # Process RUTs in parallel using ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=min(len(ruts), 5)) as executor:
            # Submit all RUTs for processing
            future_to_rut = {executor.submit(
                process_rut, rut): rut for rut in ruts}

            # Wait for all threads to complete
            for future in as_completed(future_to_rut):
                rut = future_to_rut[future]
                try:
                    future.result()  # This will raise any exceptions from the thread
                except Exception as e:
                    logging.error(f"Thread para RUT {rut} falló: {str(e)}")

        logging.info("✅ Procesamiento de todos los RUTs completado")
