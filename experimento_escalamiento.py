"""
========================================================================================
EXPERIMENTO DE ESCALAMIENTO — ¿QUÉ LIMITA REALMENTE LA LATENCIA P99?
Cátedra: Ingeniería de Software 3 [IF0129] - Corporación Universitaria Remington
Compara, con la MISMA carga (20 clientes concurrentes), tres configuraciones del servidor HTTP:
    A) ACTUAL      : http.server.HTTPServer (un solo hilo, cola de conexiones = 5)
    B) COLA GRANDE : HTTPServer con request_queue_size = 128 (sigue de un solo hilo)
    C) CON HILOS   : ThreadingHTTPServer con cola de 128
y además verifica si, con hilos, las reservas pueden SOBREVENDER cupos (condición de carrera).
No modifica el proyecto: cada variante se ejecuta en una copia temporal.
Uso: python3 experimento_escalamiento.py [--json docs/resultados_experimento.json]
Dependencias: NINGUNA (Python Standard Library)
========================================================================================
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import prueba_carga as pc

VARIANTES = {
    "A) Actual (1 hilo, cola 5)": "from http.server import HTTPServer as S",
    "B) 1 hilo, cola 128": "from http.server import HTTPServer\nclass S(HTTPServer):\n    request_queue_size = 128",
    "C) Con hilos, cola 128": "from http.server import ThreadingHTTPServer\nclass S(ThreadingHTTPServer):\n    request_queue_size = 128\n    daemon_threads = True",
}


def arrancar(tmp, nombre, definicion, cupos):
    destino = os.path.join(tmp, nombre[:1] + "_" + uuid.uuid4().hex[:6])
    shutil.copytree(pc.BASE_DIR, destino, ignore=shutil.ignore_patterns(
        "gymexpress.db*", "gymexpress_respaldo*", "__pycache__", "*.pyc"))
    puerto = pc.puerto_libre()
    codigo = (
        "import sys; sys.path.insert(0, '.')\n"
        f"{definicion}\n"
        "from src.app import GymExpressHTTPHandler, servicio_repo\n"
        f"servicio_repo.actualizar_cupos('GYM-002', 10**6)\nservicio_repo.actualizar_cupos('GYM-005', {cupos})\n"
        f"S(('127.0.0.1', {puerto}), GymExpressHTTPHandler).serve_forever()\n")
    proc = subprocess.Popen([sys.executable, "-c", codigo], cwd=destino,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(100):
        try:
            import socket
            socket.create_connection(("127.0.0.1", puerto), timeout=0.2).close()
            break
        except OSError:
            time.sleep(0.1)
    return proc, puerto


def reservas_simultaneas(puerto, n_clientes, intentos):
    def una(_):
        body = {"socio_id": "1098765432", "socio_nombre": "Carrera", "contacto": "300",
                "items": [{"codigo": "GYM-005", "cantidad": 1}], "idempotency_key": "RACE-" + uuid.uuid4().hex}
        conn = pc.http.client.HTTPConnection("127.0.0.1", puerto, timeout=60)
        try:
            conn.request("POST", "/api/reservas/saga", body=json.dumps(body), headers={"Content-Type": "application/json"})
            r = conn.getresponse()
            data = json.loads(r.read().decode())
            return data.get("exito") is True
        except Exception:
            return None
        finally:
            conn.close()
    with ThreadPoolExecutor(max_workers=n_clientes) as ex:
        return list(ex.map(una, range(intentos)))


def main():
    tmp = tempfile.mkdtemp(prefix="gym_exp_")
    resumen = []
    print("=" * 100)
    print("EXPERIMENTO DE ESCALAMIENTO — 20 clientes concurrentes")
    print("=" * 100)
    print(f"{'Variante':<28}{'Escenario':<18}{'Err.':>5}{'p50 ms':>9}{'p99 ms':>9}{'máx ms':>9}{'req/s':>9}")
    for nombre, definicion in VARIANTES.items():
        proc, puerto = arrancar(tmp, nombre, definicion, cupos=10)
        try:
            pc.peticion(puerto, "POST", "/api/gestion/suplementos/stock", {"codigo": "SUP-007", "stock": 100000})
            for i in range(30):
                pc.peticion(puerto, *pc.generar("LECTURA", i))
            fila = {"variante": nombre, "carga": []}
            for escenario in ("LECTURA", "ESCRITURA SIMPLE", "ESCRITURA SAGA"):
                r = pc.medir(puerto, escenario, 20, pc.SOLICITUDES[escenario])
                fila["carga"].append(r)
                print(f"{nombre:<28}{escenario:<18}{r['errores']:>5}{r['p50']:>9}{r['p99']:>9}{r['max']:>9}{r['throughput']:>9}")
            resultados = reservas_simultaneas(puerto, 40, 40)
            aceptadas = sum(1 for x in resultados if x is True)
            conn = pc.http.client.HTTPConnection("127.0.0.1", puerto, timeout=30)
            conn.request("GET", "/api/servicios")
            servicios = json.loads(conn.getresponse().read().decode())
            conn.close()
            cupos_final = next(s["cupos_disponibles"] for s in servicios if s["codigo"] == "GYM-005")
            fila["sobreventa"] = {"cupos_iniciales": 10, "intentos": 40, "reservas_aceptadas": aceptadas,
                                  "cupos_finales": cupos_final, "sobrevendido": aceptadas > 10 or cupos_final < 0}
            resumen.append(fila)
        finally:
            proc.terminate()
            proc.wait(timeout=10)
    # Barrido de la LÍNEA BASE (variante A: servidor original) para 1, 5, 10 y 20 clientes
    print("\nLÍNEA BASE (servidor original, cola de 5) - barrido por nivel de concurrencia")
    print(f"{'Escenario':<18}{'Conc.':>6}{'Err.':>6}{'p50 ms':>9}{'p99 ms':>9}{'máx ms':>9}{'req/s':>9}")
    linea_base = []
    proc, puerto = arrancar(tmp, "A) base", VARIANTES["A) Actual (1 hilo, cola 5)"], cupos=10)
    try:
        pc.peticion(puerto, "POST", "/api/gestion/suplementos/stock", {"codigo": "SUP-007", "stock": 100000})
        for i in range(30):
            pc.peticion(puerto, *pc.generar("LECTURA", i))
        for escenario in ("LECTURA", "ESCRITURA SIMPLE", "ESCRITURA SAGA"):
            for c in pc.NIVELES:
                r = pc.medir(puerto, escenario, c, pc.SOLICITUDES[escenario])
                linea_base.append(r)
                print(f"{escenario:<18}{c:>6}{r['errores']:>6}{r['p50']:>9}{r['p99']:>9}{r['max']:>9}{r['throughput']:>9}")
    finally:
        proc.terminate()
        proc.wait(timeout=10)

    print("\nPRUEBA DE SOBREVENTA: 40 clientes simultáneos reservan 1 cupo de un servicio con solo 10 cupos")
    for f in resumen:
        s = f["sobreventa"]
        marca = "SOBREVENTA" if s["sobrevendido"] else "correcto"
        print(f"  {f['variante']:<28} aceptadas={s['reservas_aceptadas']:>3} (máximo permitido 10)  cupos finales={s['cupos_finales']:>3}   -> {marca}")
    if "--json" in sys.argv:
        destino = sys.argv[sys.argv.index("--json") + 1]
        os.makedirs(os.path.dirname(os.path.abspath(destino)), exist_ok=True)
        with open(destino, "w", encoding="utf-8") as fh:
            json.dump({"variantes": resumen, "linea_base_A": linea_base}, fh, ensure_ascii=False, indent=2)
        print(f"\nJSON guardado en {destino}")
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
