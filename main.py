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
from typing import List, Dict
from datetime import datetime, timezone, timedelta

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
    "PresentialWork": {
        # Código postal para trabajo presencial (ej: Santiago centro)
        "postal_code": "7500000"
    },
    "HomeWork": {
        "postal_code": "9250000"  # Código postal para trabajo remoto
    }
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
    """Mapeo simple de códigos postales sin usar Google Maps API"""
    print(f"📍 Obteniendo ubicación para código postal: {postal_code}")

    # Mapeo simple basado en los códigos postales conocidos
    location_map = {
        "7500000": {  # Santiago centro
            "latitude": "-33.4489",
            "longitude": "-70.6693",
            "comuna": "Santiago"
        },
        "9250000": {  # Maipú
            "latitude": "-33.4821",
            "longitude": "-70.7514",
            "comuna": "Maipú"
        }
    }

    if postal_code in location_map:
        location_info = location_map[postal_code]
        print(f"✅ Ubicación encontrada: {location_info['comuna']}")
        return location_info
    else:
        print(
            f"⚠️ Código postal no reconocido, usando ubicación por defecto: {postal_code}")
        return {
            "latitude": "-33.4489",
            "longitude": "-70.6693",
            "comuna": "Santiago"
        }


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
    print("🎄 Verificando si hoy es feriado...")
    try:
        print("🌐 Consultando API de feriados online...")
        headers = {'accept': 'application/json'}
        response = requests.get(
            'https://api.boostr.cl/holidays.json', headers=headers, timeout=5)

        if response.status_code == 200:
            print("✅ API de feriados respondió correctamente")
            result = response.json()
            if result['status'] == 'success':
                holidays = result['data']
                today = date.today().strftime("%Y-%m-%d")
                print(f"📅 Verificando fecha: {today}")

                holiday = next(
                    (h for h in holidays if h['date'] == today), None)
                if holiday:
                    print(
                        f"🎉 ¡Hoy es feriado!: {holiday['title']} ({holiday['type']})")
                    send_holiday_email(holiday, "API")
                    return True
                else:
                    print("📅 No es feriado según API online")
            else:
                raise Exception(
                    f"API retornó estado no exitoso: {result['status']}")
        else:
            raise Exception(f"API retornó status code: {response.status_code}")

    except Exception as e:
        print(f"⚠️ API de feriados no disponible: {str(e)}")
        print("📋 Verificando con lista local de feriados...")
        # ...existing code...

        today = date.today().strftime("%Y-%m-%d")
        holiday = next(
            (h for h in CHILE_HOLIDAYS_2025 if h['date'] == today), None)

        if holiday:
            print(
                f"🎉 ¡Hoy es feriado! (lista local): {holiday['title']} ({holiday['type']})")
            send_holiday_email(holiday, "LOCAL")
            return True

    print("✅ No es feriado, continuando con el marcaje")
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


def process_rut(rut_info: Dict[str, str]) -> None:
    current_thread = threading.current_thread()
    rut = rut_info['rut']
    postal_code = rut_info['postal_code']

    # Capturar logs para el email
    log_messages = []

    try:
        log_messages.append(f"🚀 Iniciando procesamiento RUT: {rut[:4]}****")
        # Get location info (now simplified)
        print(f"📍 [Hilo {current_thread.name}] Obteniendo ubicación...")
        location_info = get_location_info(postal_code)

        # No need to check if location_info is None since we always return a default
        latitude = float(location_info['latitude'])
        longitude = float(location_info['longitude'])

        # Get Chile time
        chile_tz = timezone(timedelta(hours=-4))
        chile_time = datetime.now(chile_tz)

        print(
            f"🕐 [Hilo {current_thread.name}] Hora Chile: {chile_time.strftime('%H:%M:%S')}")

        location_type = "PresentialWork" if postal_code == LOCATIONS[
            "PresentialWork"]["postal_code"] else "HomeWork"
        comuna = location_info.get('comuna', 'Santiago')

        print(
            f"📍 [Hilo {current_thread.name}] Ubicación: {comuna} ({location_type})")

        # Determine action type
        action_type = "ENTRADA" if 5 <= chile_time.hour < 12 else "SALIDA"
        print(f"🔍 [Hilo {current_thread.name}] Tipo de marcaje: {action_type}")

        if DEBUG_MODE:
            log_messages.append("🧪 Modo DEBUG activo - simulando marcaje")
            mensaje = f"🧪 DEBUG activo: no se ejecutó marcaje. Hora Chile: {chile_time.strftime('%H:%M:%S')}"
        else:
            log_messages.append("⚡ Iniciando marcaje real...")
            print(f"⚡ [Hilo {current_thread.name}] Iniciando marcaje real...")

            # Configure Chrome options (removed geolocation setup since it's not working correctly)
            options = Options()
            options.add_argument("--headless")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--disable-gpu")
            options.add_argument("--window-size=1920,1080")

            print(f"🌐 [Hilo {current_thread.name}] Iniciando navegador...")
            driver = webdriver.Chrome(options=options)

            print(
                f"🌐 [Hilo {current_thread.name}] Cargando página de marcaje...")
            driver.get("https://app.ctrlit.cl/ctrl/dial/web/K1NBpBqyjf")
            driver.implicitly_wait(10)
            sleep(2)

            print(
                f"🔘 [Hilo {current_thread.name}] Buscando botón {action_type}...")
            boton = next((el for el in driver.find_elements(By.CSS_SELECTOR, 'button, div, span, li')
                         if el.text.strip().upper() == action_type), None)
            if not boton:
                raise Exception(f"No se encontró botón {action_type}")

            print(
                f"👆 [Hilo {current_thread.name}] Click en botón {action_type}")
            boton.click()
            sleep(2)

            print(
                f"🔢 [Hilo {current_thread.name}] Ingresando RUT: {rut[:4]}****")
            buttons = driver.find_elements(By.CSS_SELECTOR, "li.digits")
            available_buttons = [el.text.strip() for el in buttons]
            print(
                f"📱 [Hilo {current_thread.name}] Botones disponibles: {available_buttons}")

            for i, char in enumerate(rut):
                print(
                    f"🔤 [Hilo {current_thread.name}] Ingresando carácter {i+1}/{len(rut)}")
                found = False
                for el in buttons:
                    if el.text.strip().upper() == char.upper():
                        el.click()
                        found = True
                        break
                if not found:
                    raise Exception(f"No se encontró el carácter: {char}")
                sleep(0.3)

            sleep(1)

            print(f"📤 [Hilo {current_thread.name}] Enviando formulario...")
            enviar = next((el for el in driver.find_elements(By.CSS_SELECTOR, 'li.pad-action.digits')
                          if el.text.strip().upper() == "ENVIAR"), None)
            if not enviar:
                raise Exception("No se encontró botón ENVIAR")
            enviar.click()
            sleep(1)

            driver.quit()
            print(f"🌐 [Hilo {current_thread.name}] Navegador cerrado")

            # Crear mensaje con logs incluidos
            log_summary = "\n".join(log_messages[-10:])  # Últimos 10 logs
            mensaje = f"""✅ {action_type} realizada con éxito a las {chile_time.strftime('%H:%M:%S')} (Chile).

📋 LOGS DEL PROCESO:
{log_summary}"""

        print(
            f"✅ [Hilo {current_thread.name}] Marcaje completado para RUT: {rut[:4]}****")

        # Enviar correo de confirmación
        print(
            f"📧 [Hilo {current_thread.name}] Enviando correo de confirmación...")
        email = EmailMessage()
        email["From"] = EMAIL_FROM
        email["To"] = EMAIL_TO
        email["Subject"] = f"{action_type} ({location_type} - {comuna}) {'(simulada)' if DEBUG_MODE else ''} completada"
        email.set_content(mensaje)

        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as smtp:
            smtp.starttls()
            smtp.login(EMAIL_FROM, EMAIL_PASS)
            smtp.send_message(email)
        print(f"✅ [Hilo {current_thread.name}] Correo enviado exitosamente")

    except Exception as e:
        error_msg = f"""❌ Error en marcaje para RUT {rut[:4]}****:
{str(e)}

📋 LOGS DEL PROCESO:
{chr(10).join(log_messages)}"""
        print(error_msg)
        logging.error(error_msg)

        # Enviar correo de error
        print(f"📧 [Hilo {current_thread.name}] Enviando correo de error...")
        email = EmailMessage()
        email["From"] = EMAIL_FROM
        email["To"] = EMAIL_TO
        email["Subject"] = f"Error en {action_type if 'action_type' in locals() else 'MARCAJE'} ({location_type if 'location_type' in locals() else 'N/A'})"
        email.set_content(error_msg)

        try:
            with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as smtp:
                smtp.starttls()
                smtp.login(EMAIL_FROM, EMAIL_PASS)
                smtp.send_message(email)
            print(f"✅ [Hilo {current_thread.name}] Correo de error enviado")
        except Exception as mail_error:
            print(
                f"❌ [Hilo {current_thread.name}] No se pudo enviar correo de error: {str(mail_error)}")

    finally:
        print(
            f"🏁 [Hilo {current_thread.name}] Proceso finalizado para RUT: {rut[:4]}****")


def get_active_ruts() -> List[Dict[str, str]]:
    """Get all valid RUTs from LaunchDarkly flags"""
    print("🏳️ Obteniendo RUTs activos desde LaunchDarkly...")
    active_ruts = []
    try:
        context = Context.builder("default").name("default").build()
        print("🔗 Conectando con LaunchDarkly...")
        all_flags = ldclient.get().all_flags_state(context)

        if all_flags.valid:
            flags_dict = all_flags.to_json_dict()
            print(f"📊 Total de flags encontrados: {len(flags_dict)}")
            logging.info(f"Flags encontrados: {list(flags_dict.keys())}")

            valid_ruts_count = 0
            for flag_key in flags_dict:
                if not flag_key.startswith('$') and '_' in flag_key:
                    print(f"🔍 Analizando flag: {flag_key}")
                    rut, postal_code = flag_key.lower().split('_')
                    if is_valid_rut(rut):
                        rut_info = {
                            'rut': rut,
                            'postal_code': postal_code
                        }
                        active_ruts.append(rut_info)
                        valid_ruts_count += 1
                        print(
                            f"✅ RUT válido #{valid_ruts_count}: {rut[:4]}**** (código postal: {postal_code})")
                    else:
                        print(f"❌ RUT inválido en flag: {flag_key}")

            print(f"📋 Total de RUTs válidos encontrados: {len(active_ruts)}")
        else:
            print("❌ Error: Estado de flags de LaunchDarkly no válido")

        return active_ruts
    except Exception as e:
        print(f"❌ Error obteniendo RUTs: {str(e)}")
        logging.error(f"Error obteniendo RUTs: {str(e)}")
        return []


def get_random_delay() -> int:
    """Genera un delay aleatorio entre 1 y 20 minutos"""
    delay_minutes = random.randint(1, 20)
    logging.info(f"⏰ Delay aleatorio generado: {delay_minutes} minutos")
    return delay_minutes


# Verificar si debemos ejecutar el script
if __name__ == "__main__":
    print("=" * 60)
    print("🚀 INICIANDO SCRIPT DE MARCAJE AUTOMÁTICO")
    print("=" * 60)

    print("🔍 Verificando configuración inicial...")
    if not CLOCK_IN_ACTIVE:
        print("⏹️ Script desactivado por variable CLOCK_IN_ACTIVE")
        logging.info(
            "Script desactivado por variable de entorno CLOCK_IN_ACTIVE")
        exit()

    print("✅ Script activo, continuando...")

    if is_holiday():
        print("🎄 Terminando ejecución - hoy es feriado")
        exit()

    # Agregar delay aleatorio solo si no está en modo debug
    if not DEBUG_MODE:
        delay_minutes = 0  # get_random_delay()
        print(f"⏰ Aplicando delay aleatorio: {delay_minutes} minutos")
        print(f"⏳ Esperando para simular comportamiento humano...")
        logging.info(
            f"Aplicando delay de {delay_minutes} minutos en modo producción")
        sleep(delay_minutes * 60)  # Convertir minutos a segundos
        print("✅ Delay completado, continuando...")
    else:
        print("🔄 Modo DEBUG activo: ejecutando inmediatamente")
        logging.info("Ejecutando en modo DEBUG: sin delay aleatorio")

    print("🔍 Obteniendo lista de RUTs para procesar...")
    ruts = get_active_ruts()

    if not ruts:
        print("❌ No se encontraron RUTs válidos para procesar")
        print("🏁 Finalizando script")
    else:
        print("=" * 40)
        print(f"👥 INICIANDO PROCESAMIENTO DE {len(ruts)} RUTs")
        print("=" * 40)

        with ThreadPoolExecutor(max_workers=min(len(ruts), 5)) as executor:
            print(f"🧵 Usando {min(len(ruts), 5)} hilos paralelos")
            futures = []

            for i, rut_info in enumerate(ruts):
                print(
                    f"🚀 Enviando RUT {i+1}/{len(ruts)} al pool de hilos: {rut_info['rut'][:4]}****")
                future = executor.submit(process_rut, rut_info)
                futures.append((future, rut_info))

            print("⏳ Esperando completación de todos los hilos...")
            completed = 0
            for future, rut_info in futures:
                try:
                    future.result()
                    completed += 1
                    print(
                        f"✅ Completado {completed}/{len(futures)} - RUT: {rut_info['rut'][:4]}****")
                except Exception as e:
                    completed += 1
                    print(
                        f"❌ Error {completed}/{len(futures)} - RUT: {rut_info['rut'][:4]}****: {str(e)}")

        print("=" * 40)
        print("🎉 PROCESAMIENTO COMPLETADO")
        print("=" * 40)
        print(f"📊 RUTs procesados: {len(ruts)}")
        print("🏁 Script finalizado exitosamente")
