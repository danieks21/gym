"""
Reinicia la base de datos del proyecto para que se vuelva a crear con los datos iniciales.
Antes de borrarla, guarda una copia de respaldo (gymexpress_respaldo_AAAAMMDD_HHMMSS.db).
Uso:  python3 reiniciar_bd.py     (con el servidor detenido)
"""
import os
import shutil
import sqlite3
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "gymexpress.db")

if not os.path.exists(DB_PATH):
    print("No hay base de datos que reiniciar: se creará sola al ejecutar main.py.")
else:
    respaldo = os.path.join(BASE_DIR, time.strftime("gymexpress_respaldo_%Y%m%d_%H%M%S.db"))
    origen = sqlite3.connect(DB_PATH)
    destino = sqlite3.connect(respaldo)
    origen.backup(destino)          # copia consistente aunque exista el archivo -wal
    destino.close()
    origen.close()
    for sufijo in ("", "-wal", "-shm"):
        if os.path.exists(DB_PATH + sufijo):
            os.remove(DB_PATH + sufijo)
    print(f"Respaldo guardado en: {respaldo}")
    print("Base de datos eliminada. Ejecuta `python3 main.py` para recrearla con los datos iniciales.")
