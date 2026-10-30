"""
========================================================================================
SCRIPT DE AUDITORÍA ARQUITECTÓNICA — MÉTRICAS DE ROBERT C. MARTIN
Cátedra: Ingeniería de Software 3 [IF0129] - Corporación Universitaria Remington
Entregable 2 (Actividad 1): cálculo de Inestabilidad y Distancia por módulo + verificación
automática de SoD y DIP.

Qué calcula (cada módulo .py de src/ más main.py es una "unidad", como pide la guía):
    Ca  Acoplamiento aferente : cuántos módulos DEL PROYECTO dependen de este.
    Ce  Acoplamiento eferente : de cuántos módulos DEL PROYECTO depende este.
    I   Inestabilidad         : I = Ce / (Ca + Ce)      (0 = estable, 1 = inestable)
    A   Abstracción           : clases abstractas / total de clases del módulo
    D   Distancia             : D = |A + I - 1|          (0 = sobre la secuencia principal)
Las dependencias hacia la biblioteca estándar NO cuentan (son estables por definición).

Uso:   python3 auditoria_metricas.py            # tabla + reglas en consola
       python3 auditoria_metricas.py --json docs/auditoria_metricas.json
Dependencias: NINGUNA (Python Standard Library `ast`, `json`, `os`, `sys`)
========================================================================================
"""
import ast
import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.join(BASE_DIR, "src")

# Módulos con permiso para tocar infraestructura (reglas de SoD)
PERMITE_SQLITE = {"src.db", "src.repositories", "src.repositories_extra", "src.db_viewer"}
PERMITE_HTTP = {"src.app", "src.app_extras"}
COMPOSITION_ROOTS = {"src.app", "src.app_extras"}   # únicos que "cablean" repos concretos
CAPA_SERVICIOS = {"src.services", "src.services_extra"}
REPOS_CONCRETOS = {"src.repositories", "src.repositories_extra"}
UMBRAL_D = 0.30


def descubrir_modulos():
    mods = {}
    for nombre in sorted(os.listdir(SRC_DIR)):
        if nombre.endswith(".py") and nombre != "__init__.py":
            mods["src." + nombre[:-3]] = os.path.join(SRC_DIR, nombre)
    mods["main"] = os.path.join(BASE_DIR, "main.py")
    return mods


def importaciones(ruta):
    """Devuelve (módulos_del_proyecto_importados, módulos_externos_importados)."""
    arbol = ast.parse(open(ruta, encoding="utf-8").read())
    internos, externos = set(), set()
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.ImportFrom) and nodo.module:
            destino = nodo.module
            if destino == "src":                       # from src import x
                internos.update("src." + a.name for a in nodo.names)
            elif destino.startswith("src."):
                internos.add(destino)
            else:
                externos.add(destino.split(".")[0])
        elif isinstance(nodo, ast.Import):
            for a in nodo.names:
                (internos if a.name.startswith("src.") else externos).add(
                    a.name if a.name.startswith("src.") else a.name.split(".")[0])
    return internos, externos


def abstraccion(ruta):
    """(clases_abstractas, total_clases) a nivel de módulo."""
    arbol = ast.parse(open(ruta, encoding="utf-8").read())
    total = abstractas = 0
    for nodo in arbol.body:
        if isinstance(nodo, ast.ClassDef):
            total += 1
            hereda_abc = any(getattr(b, "id", getattr(b, "attr", "")) == "ABC" for b in nodo.bases)
            tiene_abstractos = any(
                isinstance(f, ast.FunctionDef) and any(
                    getattr(d, "id", getattr(d, "attr", "")) == "abstractmethod" for d in f.decorator_list)
                for f in nodo.body)
            if hereda_abc or tiene_abstractos:
                abstractas += 1
    return abstractas, total


def ciclos(grafo):
    """Detecta ciclos de dependencia (Principio de Dependencias Acíclicas)."""
    encontrados, visitados, pila = [], set(), []

    def dfs(n):
        if n in pila:
            encontrados.append(pila[pila.index(n):] + [n])
            return
        if n in visitados:
            return
        visitados.add(n)
        pila.append(n)
        for v in sorted(grafo.get(n, ())):
            dfs(v)
        pila.pop()

    for n in sorted(grafo):
        dfs(n)
    return encontrados


def zona(a, i, d, total_clases):
    if total_clases == 0:
        return "Sin clases (funciones/constantes)"
    if d <= UMBRAL_D:
        return "Cercano a la secuencia principal"
    if a + i < 1:
        return "Zona de dolor (estable y concreto)"
    return "Zona de inutilidad (abstracto e inestable)"


def auditar():
    mods = descubrir_modulos()
    deps, externos = {}, {}
    for m, ruta in mods.items():
        internos, ext = importaciones(ruta)
        deps[m] = {x for x in internos if x in mods and x != m}
        externos[m] = ext

    ca = {m: sum(1 for o in deps if m in deps[o]) for m in mods}
    ce = {m: len(deps[m]) for m in mods}
    filas = {}
    for m, ruta in mods.items():
        abst, total = abstraccion(ruta)
        i = ce[m] / (ca[m] + ce[m]) if (ca[m] + ce[m]) else 0.0
        a = abst / total if total else 0.0
        d = abs(a + i - 1)
        filas[m] = {"modulo": m, "Ca": ca[m], "Ce": ce[m], "I": round(i, 2), "clases": total,
                    "abstractas": abst, "A": round(a, 2), "D": round(d, 2),
                    "zona": zona(a, i, d, total),
                    "depende_de": sorted(deps[m]), "usado_por": sorted(o for o in deps if m in deps[o])}

    # ------------------- reglas arquitectónicas verificables -------------------
    reglas = []

    def regla(nombre, principio, violaciones):
        reglas.append({"regla": nombre, "principio": principio, "cumple": not violaciones, "violaciones": violaciones})

    regla("Los servicios no importan repositorios concretos (solo interfaces)", "DIP",
          sorted(f"{s} -> {r}" for s in CAPA_SERVICIOS for r in REPOS_CONCRETOS if r in deps.get(s, ())))
    regla("Las interfaces no dependen de servicios, repositorios ni de la capa web", "DIP",
          sorted(f"{m} -> {x}" for m in mods if m.startswith("src.interfaces") for x in deps[m]
                 if x in CAPA_SERVICIOS | REPOS_CONCRETOS | PERMITE_HTTP))
    regla("Los modelos de dominio no dependen de ningún otro módulo del proyecto", "DIP / SRP",
          sorted(f"{m} -> {x}" for m in mods if m.startswith("src.models") for x in deps[m]))
    regla("Solo los composition roots (app, app_extras) instancian repositorios concretos", "DIP",
          sorted(f"{m} -> {r}" for m in mods for r in REPOS_CONCRETOS
                 if r in deps[m] and m not in COMPOSITION_ROOTS))
    regla("Solo los repositorios (y db/db_viewer) importan sqlite3", "SoD",
          sorted(m for m in mods if "sqlite3" in externos[m] and m not in PERMITE_SQLITE))
    regla("Solo la capa web (app, app_extras) importa http.server", "SoD",
          sorted(m for m in mods if "http" in externos[m] and m not in PERMITE_HTTP))
    regla("Los servicios y validadores no importan la capa web", "SoD",
          sorted(f"{m} -> {x}" for m in mods if (m in CAPA_SERVICIOS or m.startswith("src.validators"))
                 for x in deps[m] if x in PERMITE_HTTP | {"src.pages_extra"}))
    sdp = sorted(f"{m} (I={filas[m]['I']}) -> {x} (I={filas[x]['I']})" for m in mods for x in deps[m]
                 if filas[x]["I"] > filas[m]["I"])
    regla("Principio de Dependencias Estables: se depende de módulos más estables", "SDP", sdp)
    regla("Sin ciclos de dependencia entre módulos", "ADP", [" -> ".join(c) for c in ciclos(deps)])

    return {"modulos": filas, "reglas": reglas}


def imprimir(res):
    f = res["modulos"]
    print("=" * 108)
    print("AUDITORÍA DE MÉTRICAS DE ROBERT C. MARTIN — GymExpress")
    print("=" * 108)
    print(f"{'Módulo':<26}{'Ca':>3}{'Ce':>4}{'I':>6}{'Clases':>8}{'Abs.':>6}{'A':>6}{'D':>6}   Zona")
    print("-" * 108)
    for m in sorted(f, key=lambda k: (-f[k]["D"], k)):
        r = f[m]
        print(f"{m:<26}{r['Ca']:>3}{r['Ce']:>4}{r['I']:>6.2f}{r['clases']:>8}{r['abstractas']:>6}{r['A']:>6.2f}{r['D']:>6.2f}   {r['zona']}")
    n = len(f)
    print("-" * 108)
    print(f"Promedios: I = {sum(r['I'] for r in f.values())/n:.2f}   A = {sum(r['A'] for r in f.values())/n:.2f}"
          f"   D = {sum(r['D'] for r in f.values())/n:.2f}   ({n} módulos; umbral D <= {UMBRAL_D})")
    con_clases = [r for r in f.values() if r["clases"] > 0]
    print(f"Solo módulos con clases ({len(con_clases)}): D promedio = {sum(r['D'] for r in con_clases)/len(con_clases):.2f}"
          "   (D no es significativo para módulos sin clases)")
    print()
    print("VERIFICACIÓN AUTOMÁTICA DE REGLAS (SoD / DIP / SDP / ADP)")
    print("-" * 108)
    for r in res["reglas"]:
        print(f"[{'CUMPLE ' if r['cumple'] else 'VIOLA  '}] ({r['principio']}) {r['regla']}")
        for v in r["violaciones"]:
            print(f"           ! {v}")
    ok = sum(r["cumple"] for r in res["reglas"])
    print(f"\nResultado: {ok}/{len(res['reglas'])} reglas cumplidas.")


if __name__ == "__main__":
    resultado = auditar()
    imprimir(resultado)
    if "--json" in sys.argv:
        destino = sys.argv[sys.argv.index("--json") + 1]
        os.makedirs(os.path.dirname(os.path.abspath(destino)), exist_ok=True)
        with open(destino, "w", encoding="utf-8") as fh:
            json.dump(resultado, fh, ensure_ascii=False, indent=2)
        print(f"JSON guardado en {destino}")
