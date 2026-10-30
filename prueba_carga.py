"""
========================================================================================
PRUEBA DE CARGA Y DIAGNÓSTICO DE PERSISTENCIA — LATENCIA P99 Y CUELLOS DE BOTELLA
Cátedra: Ingeniería de Software 3 [IF0129] - Corporación Universitaria Remington
Entregable 3 (Actividad 1): mide con datos reales (no supuestos) el comportamiento de la
persistencia SQLite síncrona y del servidor HTTP, para fundamentar los SLO.

Qué hace:
  1. Copia el proyecto a una carpeta temporal (NO toca tu gymexpress.db) y levanta el servidor allí.
  2. Lanza clientes concurrentes (1, 5, 10 y 20) contra tres tipos de operación:
       LECTURA          GET  /api/servicios | /api/entrenadores | /api/suplementos
       ESCRITURA SIMPLE POST /api/suplementos/consumo      (1 transacción atómica)
       ESCRITURA SAGA   POST /api/reservas/saga            (flujo de reservas T1->T2->T3)
  3. Calcula p50, p95, p99, máximo, throughput y tasa de error.
  4. Diagnóstico interno: conexiones SQLite abiertas por operación y costo del commit
     con synchronous = FULL / NORMAL / OFF.

Uso:   python3 prueba_carga.py                       # prueba completa
       python3 prueba_carga.py --json docs/resultados_carga.json
Dependencias: NINGUNA (Python Standard Library)
========================================================================================
"""
import http.client
import json
import math
import os
import platform
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
NIVELES = [1, 5, 10, 20]
SOLICITUDES = {"LECTURA": 400, "ESCRITURA SIMPLE": 200, "ESCRITURA SAGA": 120}
RUTAS_LECTURA = ["/api/servicios", "/api/entrenadores", "/api/suplementos"]


def puerto_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def percentil(datos, p):
    """Percentil por el método del rango más cercano (nearest-rank)."""
    ordenados = sorted(datos)
    k = max(0, math.ceil(p / 100 * len(ordenados)) - 1)
    return ordenados[k]


def peticion(puerto, metodo, ruta, cuerpo=None):
    t0 = time.perf_counter()
    try:
        conn = http.client.HTTPConnection("127.0.0.1", puerto, timeout=60)
        headers = {"Content-Type": "application/json"} if cuerpo is not None else {}
        conn.request(metodo, ruta, body=json.dumps(cuerpo) if cuerpo is not None else None, headers=headers)
        resp = conn.getresponse()
        resp.read()
        estado = resp.status
        conn.close()
    except Exception:
        estado = 0
    return (time.perf_counter() - t0) * 1000, estado


def generar(escenario, i):
    if escenario == "LECTURA":
        return "GET", RUTAS_LECTURA[i % len(RUTAS_LECTURA)], None
    if escenario == "ESCRITURA SIMPLE":
        return "POST", "/api/suplementos/consumo", {
            "socio_id": "1098765432", "socio_nombre": "Carga", "codigo": "SUP-007", "cantidad": 1,
            "idempotency_key": "LOAD-" + uuid.uuid4().hex}
    return "POST", "/api/reservas/saga", {
        "socio_id": "1098765432", "socio_nombre": "Carga", "contacto": "3000000000",
        "items": [{"codigo": "GYM-002", "cantidad": 1}], "idempotency_key": "LOAD-" + uuid.uuid4().hex}


def medir(puerto, escenario, concurrencia, n):
    tareas = [generar(escenario, i) for i in range(n)]
    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrencia) as ex:
        resultados = list(ex.map(lambda t: peticion(puerto, *t), tareas))
    duracion = time.perf_counter() - t0
    lat = [r[0] for r in resultados]
    errores = sum(1 for r in resultados if r[1] != 200)
    detalle = {}
    for r in resultados:
        if r[1] != 200:
            detalle[str(r[1])] = detalle.get(str(r[1]), 0) + 1       # 0 = conexión rechazada / reiniciada / timeout
    return {"escenario": escenario, "concurrencia": concurrencia, "solicitudes": n, "errores": errores,
            "errores_por_estado": detalle,
            "p50": round(percentil(lat, 50), 1), "p95": round(percentil(lat, 95), 1),
            "p99": round(percentil(lat, 99), 1), "max": round(max(lat), 1),
            "throughput": round(n / duracion, 1)}


def levantar_servidor(tmp):
    """Copia el proyecto y arranca el servidor con una BD de pruebas con cupos holgados."""
    destino = os.path.join(tmp, "proyecto")
    shutil.copytree(BASE_DIR, destino, ignore=shutil.ignore_patterns(
        "gymexpress.db*", "gymexpress_respaldo*", "__pycache__", "*.pyc"))
    puerto = puerto_libre()
    codigo = (
        "import sys; sys.path.insert(0, '.');"
        "from src.app import run_server, servicio_repo;"
        "servicio_repo.actualizar_cupos('GYM-002', 10**6);"
        f"run_server(port={puerto})")
    proc = subprocess.Popen([sys.executable, "-c", codigo], cwd=destino,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(100):
        try:
            socket.create_connection(("127.0.0.1", puerto), timeout=0.2).close()
            break
        except OSError:
            time.sleep(0.1)
    peticion(puerto, "POST", "/api/gestion/suplementos/stock", {"codigo": "SUP-007", "stock": 100000})
    for i in range(30):                                   # calentamiento (no se mide)
        peticion(puerto, *generar("LECTURA", i))
    return proc, puerto, destino


def diagnostico_conexiones(destino):
    """Cuenta cuántas conexiones SQLite abre cada operación de negocio."""
    sys.path.insert(0, destino)
    for m in [m for m in sys.modules if m == "src" or m.startswith("src.")]:
        del sys.modules[m]
    tmpdb = os.path.join(destino, "diag.db")
    from src.repositories import SQLiteServicioRepository, SQLiteReservaRepository, SQLiteOutboxRepository
    from src.repositories_extra import SQLiteSuplementoRepository
    from src.services import GimnasioService, PasarelaPagosMock, SagaOrquestadorReserva
    from src.services_extra import SuplementoService
    srepo, rrepo, orepo = SQLiteServicioRepository(tmpdb), SQLiteReservaRepository(tmpdb), SQLiteOutboxRepository(tmpdb)
    saga = SagaOrquestadorReserva(GimnasioService(srepo, rrepo, orepo), PasarelaPagosMock())
    sup = SuplementoService(SQLiteSuplementoRepository(tmpdb))
    contador = {"n": 0}
    original = sqlite3.connect

    def contado(*a, **k):
        contador["n"] += 1
        return original(*a, **k)

    sqlite3.connect = contado
    casos = {
        "Lectura: listar catálogo": lambda: srepo.obtener_todos(),
        "Escritura: consumo de suplemento": lambda: sup.consumir("1098765432", "Diag", "SUP-007", 1, "DIAG-" + uuid.uuid4().hex),
        "Saga de reserva exitosa (T1+T2+T3)": lambda: saga.ejecutar_saga_reserva(
            "1098765432", "Diag", "300", [{"codigo": "GYM-001", "cantidad": 1}], "DIAG-" + uuid.uuid4().hex),
        "Saga con falla de pago (T1+C1)": lambda: saga.ejecutar_saga_reserva(
            "1098765432", "Diag", "300", [{"codigo": "GYM-001", "cantidad": 1}], "DIAG-" + uuid.uuid4().hex,
            simular_falla_pago=True),
    }
    salida = []
    for nombre, fn in casos.items():
        contador["n"] = 0
        t0 = time.perf_counter()
        fn()
        ms = (time.perf_counter() - t0) * 1000
        salida.append({"operacion": nombre, "conexiones": contador["n"], "ms": round(ms, 2)})
    sqlite3.connect = original
    return salida


def costo_commit(tmp, repeticiones=200):
    """ms por transacción según PRAGMA synchronous y según se abra una conexión nueva o se reutilice una."""
    salida = []
    for modo in ("FULL", "NORMAL", "OFF"):
        for estrategia in ("nueva por transacción", "persistente"):
            ruta = os.path.join(tmp, f"commit_{modo}_{estrategia[:3]}.db")
            c = sqlite3.connect(ruta)
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v INTEGER)")
            c.execute("INSERT INTO t VALUES (1, 0)")
            c.commit()
            if estrategia == "nueva por transacción":
                c.close()
            else:
                c.execute(f"PRAGMA synchronous={modo}")
            t0 = time.perf_counter()
            for _ in range(repeticiones):
                if estrategia == "nueva por transacción":
                    c = sqlite3.connect(ruta)
                    c.execute(f"PRAGMA synchronous={modo}")
                c.execute("UPDATE t SET v = v + 1 WHERE id = 1")
                c.commit()
                if estrategia == "nueva por transacción":
                    c.close()
            ms = (time.perf_counter() - t0) * 1000 / repeticiones
            if estrategia == "persistente":
                c.close()
            salida.append({"synchronous": modo, "conexion": estrategia, "ms_por_transaccion": round(ms, 3)})
    return salida


def main():
    entorno = {"fecha": time.strftime("%Y-%m-%d %H:%M:%S"), "python": platform.python_version(),
               "sistema": f"{platform.system()} {platform.release()}", "cpus": os.cpu_count(),
               "sqlite": sqlite3.sqlite_version}
    print("=" * 100)
    print("PRUEBA DE CARGA — GymExpress  |  ", entorno)
    print("=" * 100)
    tmp = tempfile.mkdtemp(prefix="gym_carga_")
    proc, puerto, destino = levantar_servidor(tmp)
    resultados = []
    try:
        print(f"{'Escenario':<18}{'Conc.':>6}{'Solic.':>8}{'Err.':>6}{'p50 ms':>9}{'p95 ms':>9}{'p99 ms':>9}{'máx ms':>9}{'req/s':>9}")
        print("-" * 100)
        for escenario, n in SOLICITUDES.items():
            for c in NIVELES:
                r = medir(puerto, escenario, c, n)
                resultados.append(r)
                print(f"{r['escenario']:<18}{r['concurrencia']:>6}{r['solicitudes']:>8}{r['errores']:>6}"
                      f"{r['p50']:>9}{r['p95']:>9}{r['p99']:>9}{r['max']:>9}{r['throughput']:>9}"
                      + (f"   errores por estado HTTP: {r['errores_por_estado']}" if r['errores'] else ""))
            print("-" * 100)
    finally:
        proc.terminate()
        proc.wait(timeout=10)
    conexiones = diagnostico_conexiones(destino)
    commits = costo_commit(tmp)
    print("\nDIAGNÓSTICO DE PERSISTENCIA — conexiones SQLite abiertas por operación (1 cliente)")
    for c in conexiones:
        print(f"  {c['operacion']:<40} {c['conexiones']:>3} conexiones   {c['ms']:>8} ms")
    print("\nCOSTO DE UNA TRANSACCIÓN (UPDATE + commit, modo WAL)")
    for c in commits:
        print(f"  synchronous={c['synchronous']:<7} conexión {c['conexion']:<22} {c['ms_por_transaccion']:>8} ms/transacción")
    if "--json" in sys.argv:
        destino_json = sys.argv[sys.argv.index("--json") + 1]
        os.makedirs(os.path.dirname(os.path.abspath(destino_json)), exist_ok=True)
        with open(destino_json, "w", encoding="utf-8") as fh:
            json.dump({"entorno": entorno, "carga": resultados, "conexiones": conexiones, "commit": commits},
                      fh, ensure_ascii=False, indent=2)
        print(f"\nJSON guardado en {destino_json}")
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
