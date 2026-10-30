"""
========================================================================================
PUNTO DE ENTRADA PRINCIPAL: GYMEXPRESS WEB MVP
Cátedra: Ingeniería de Software 3 [IF0129] - Corporación Universitaria Remington
Docente: Ing. Jhon Alexander Rosero Lasso, MSc en Inteligencia Artificial
Patrones: Clean Architecture, SOLID, ACID Local, SoD, Saga Orchestrator
Tecnología: Python 3.10+ Standard Library (CERO DEPENDENCIAS / CERO PIP INSTALL)
========================================================================================
"""
import os
import sys
import threading
import time
import subprocess
import webbrowser

# Configuración del PYTHONPATH para ejecución portable en cualquier entorno (Linux, Windows, WSL)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from src.app import run_server
from src.logger import get_logger

logger = get_logger("Main")

def abrir_navegador(url: str, delay: float = 0.8):
    """
    Abre el navegador web del sistema con detección inteligente de WSL2 / Linux / Windows:
    1. Si está en WSL2 y no hay GUI Linux, usa explorer.exe o powershell.exe de Windows.
    2. Si tiene navegador Linux nativo, usa webbrowser.open().
    3. Si es un entorno headless (sin entorno gráfico), captura el evento limpiamente
       sin emitir mensajes de error 'xdg-open not found'.
    """
    time.sleep(delay)
    
    # 1. Detección de entorno WSL2
    es_wsl = False
    try:
        if os.path.exists("/proc/version"):
            with open("/proc/version", "r") as f:
                if "microsoft" in f.read().lower():
                    es_wsl = True
    except Exception:
        pass

    if es_wsl:
        # Intentar invocar el navegador predeterminado del Windows host
        try:
            # cmd.exe /c start <url> o explorer.exe <url>
            if os.path.exists("/mnt/c/Windows/System32/cmd.exe"):
                subprocess.Popen(
                    ["/mnt/c/Windows/System32/cmd.exe", "/c", "start", url],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                logger.info(f"🌐 [WSL2 Host] Abriendo GymExpress en el navegador de Windows: {url}")
                return
        except Exception:
            pass

    # 2. Intento estándar multiplataforma
    try:
        # Desviar stderr temporalmente para evitar el volcado de xdg-open en entornos sin X11/Wayland
        devnull = open(os.devnull, 'w')
        old_stderr = os.dup(2)
        os.dup2(devnull.fileno(), 2)
        
        abierto = webbrowser.open(url)
        
        os.dup2(old_stderr, 2)
        os.close(old_stderr)
        devnull.close()

        if abierto:
            logger.info(f"🌐 GymExpress abierto en navegador local: {url}")
        else:
            logger.info(f"ℹ️ Servidor listo. Abre manualmente en tu navegador: {url}")
    except Exception:
        logger.info(f"ℹ️ Entorno sin GUI detectado. Abre manualmente en tu navegador: {url}")


if __name__ == "__main__":
    PORT = 8086
    URL = f"http://localhost:{PORT}/panel"

    print("=" * 85)
    print("🏋️ GYMEXPRESS MVP — INGENIERÍA DE SOFTWARE 3 [IF0129]")
    print("Corporación Universitaria Remington — Facultad de Ingenierías")
    print("Docente: Ing. Jhon Alexander Rosero Lasso, MSc en IA")
    print("Patrones: SOLID | ACID (SQLite WAL) | Saga Orchestrator | Outbox Pattern | Fail-Fast")
    print(f"🔗 Servidor Web y API REST activo en: {URL}")
    print(f"🧭 Panel integrado: {URL}")
    print(f"🧑‍🏫 Portal del socio: http://localhost:{PORT}/usuario   |   🛠️ Panel interno: http://localhost:{PORT}/gestion")
    print(f"🗄️ Ver la base de datos: http://localhost:{PORT}/basedatos   (o: python3 ver_bd.py)")
    print("🧪 Suite de pruebas automatizadas: python3 -m unittest discover -s tests -p 'test_*.py'")
    print("=" * 85)

    # Iniciar subproceso de apertura de interfaz web resiliente
    threading.Thread(target=abrir_navegador, args=(URL,), daemon=True).start()
    
    # Lanzar servidor HTTP nativo
    run_server(port=PORT)
