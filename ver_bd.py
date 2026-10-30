"""
Muestra en la terminal TODO el contenido de la base de datos del proyecto (solo lectura).
Uso:  python3 ver_bd.py            -> todas las tablas
      python3 ver_bd.py suplementos -> una tabla
Dependencias: ninguna (Python Standard Library).
"""
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
from src.db_viewer import VisorBD

DB_PATH = os.path.join(BASE_DIR, "gymexpress.db")


def mostrar(visor: VisorBD, nombre: str):
    d = visor.leer_tabla(nombre, 500)
    print(f"\n=== {d['tabla']} ({d['total']} filas) ===")
    anchos = [len(c) for c in d["columnas"]]
    filas = [[("NULL" if v is None else str(v))[:40] for v in f] for f in d["filas"]]
    for f in filas:
        anchos = [max(a, len(v)) for a, v in zip(anchos, f)]
    print(" | ".join(c.ljust(a) for c, a in zip(d["columnas"], anchos)))
    print("-+-".join("-" * a for a in anchos))
    for f in filas:
        print(" | ".join(v.ljust(a) for v, a in zip(f, anchos)))


if __name__ == "__main__":
    if not os.path.exists(DB_PATH):
        sys.exit("Aún no existe gymexpress.db: ejecuta primero `python3 main.py` una vez.")
    visor = VisorBD(DB_PATH)
    print("Base de datos:", visor.db_path)
    nombres = sys.argv[1:] or [t["nombre"] for t in visor.resumen()["tablas"]]
    for n in nombres:
        mostrar(visor, n)
