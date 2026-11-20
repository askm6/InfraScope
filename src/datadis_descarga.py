"""Descarga el consumo eléctrico mensual por municipio y sector desde Datadis.

Usa la consulta pública de https://datadis.es/queries (no hace falta registrarse).
Datadis solo deja consultar un mes por petición y su servidor es lento (10-30 s por
consulta), así que el proceso va en dos pasos:

  1. Descarga: cada respuesta se guarda en un JSON por municipio
     (data/raw/energia/datadis_<codigo_ine>.json). Si se corta, al relanzarlo
     sigue donde se quedó. Los JSON están en .gitignore: cada uno los genera en local.
  2. Unión: junta todos los JSON en un único CSV
     (data/raw/energia/datadis_consumo_municipios_mensual.csv) y, si no falta nada,
     borra los JSON.

Uso:
    python src/datadis_descarga.py                          # 2022-01 hasta el mes pasado
    python src/datadis_descarga.py --desde 2025-01 --hasta 2025-12
    python src/datadis_descarga.py --solo-csv               # solo junta los JSON que haya
    python src/datadis_descarga.py --conservar-json         # no borra los JSON al final
"""
import argparse
import csv
import glob
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pandas as pd
import requests

# ---------------- Configuración ----------------
RUTA_MUNICIPIOS = "data/processed/municipios.csv"      # lista maestra: codigo_ine, municipio
CARPETA = "data/raw/energia/"
PATRON_JSON = CARPETA + "datadis_{}.json"              # un JSON por municipio (en .gitignore)
RUTA_SALIDA = CARPETA + "datadis_consumo_municipios_mensual.csv"
URL = "https://datadis.es/api-public"
HILOS = 4                       # consultas en paralelo (más no acelera: el servidor encola)
REINTENTOS = 3
try:
    ZONA = ZoneInfo("Europe/Madrid")
except ZoneInfoNotFoundError:           # Windows sin el paquete tzdata: hora de invierno fija
    ZONA = timezone(timedelta(hours=1))
# Sectores de Datadis. "T" = total del mes sin desglose (consultas sin filtro de sector)
SECTORES = {"1": "RESIDENCIAL", "2": "INDUSTRIA", "3": "SERVICIOS", "4": "NO ESPECIFICADO"}
COLUMNAS = ["codigo_ine", "municipio", "anio", "mes", "sector", "energia_kwh", "contratos"]

sesion = requests.Session()
sesion.headers.update({"Content-Type": "application/json", "User-Agent": "Proyecto3-CPD/1.0"})
candado = threading.Lock()


def post(ruta, cuerpo):
    r = sesion.post(f"{URL}/{ruta}", json=cuerpo, timeout=120)
    r.raise_for_status()
    datos = r.json()
    return datos.get("response", datos) if isinstance(datos, dict) else datos


def localizaciones(codigos):
    """Objetos de comunidad, provincia y municipio tal y como los pide Datadis."""
    comunidades = sesion.get(f"{URL}/combo/community", timeout=60).json()["response"]
    provincias = post("combo/province", {"communities": comunidades})
    necesarias = [p for p in provincias if p["numericCode"] in {c[:2] for c in codigos}]
    municipios = post("combo/municipality", {"provinces": necesarias})
    res = {}
    for cod in codigos:
        prov = next(p for p in provincias if p["numericCode"] == cod[:2])
        muni = next((m for m in municipios if m["province"] == cod[:2] and m["code"] == cod[2:]), None)
        if muni is None:
            print(f"Aviso: {cod} no está en Datadis")
            continue
        com = next(c for c in comunidades if c["code"] == prov["communityCode"])
        res[cod] = (com, prov, muni)
    return res


def ms(anio, mes, dia):
    """Fecha a milisegundos, a la 01:00 hora de Madrid (igual que la web de Datadis)."""
    return int(datetime(anio, mes, dia, 1, tzinfo=ZONA).timestamp() * 1000)


def consultar(loc, anio, mes, sector):
    """Energía (kWh) y nº de contratos de un municipio, mes y sector. -1 = sin dato."""
    com, prov, muni = loc
    ultimo = (date(anio + (mes == 12), mes % 12 + 1, 1) - date(anio, mes, 1)).days
    filtros = [
        {"property": "dataDay", "value": ms(anio, mes, 1), "operator": "<"},
        {"property": "dataDay", "value": ms(anio, mes, ultimo), "operator": ">"},
        {"property": "community", "operator": "in", "value": [com]},
        {"property": "province", "operator": "in", "value": [prov]},
        {"property": "municipality", "operator": "in", "value": [muni]},
    ]
    if sector != "T":
        filtros.append({"property": "economicSector", "operator": "in",
                        "value": [{"code": sector, "description": SECTORES[sector]}]})
    cuerpo = {"filter": None, "limit": 1, "page": 1, "sort": None, "sortParams": [], "start": None,
              "filterParams": filtros}
    for intento in range(REINTENTOS):
        try:
            r = post("dataset/searchSumContractsAndEnergy", cuerpo)
            return {"energia_kwh": r["energy"], "contratos": r["contracts"]}
        except (requests.RequestException, KeyError, ValueError):
            time.sleep(5 * (intento + 1))
    return None


def leer_json(codigo):
    ruta = PATRON_JSON.format(codigo)
    if os.path.exists(ruta):
        with open(ruta, encoding="utf-8") as f:
            return json.load(f)
    return {"codigo_ine": codigo, "consultas": {}}


def guardar_json(datos):
    ruta = PATRON_JSON.format(datos["codigo_ine"])
    with open(ruta + ".tmp", "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(ruta + ".tmp", ruta)              # escritura atómica: un corte no deja el JSON roto


def meses(desde, hasta):
    a, m = desde
    while (a, m) <= hasta:
        yield a, m
        a, m = (a + 1, 1) if m == 12 else (a, m + 1)


def descargar(nombres, desde, hasta):
    """Paso 1: descarga lo que falte y lo va guardando en los JSON. Devuelve nº de fallos."""
    locs = localizaciones(list(nombres))
    cache = {c: leer_json(c) for c in locs}
    for c in cache:
        cache[c]["municipio"] = nombres[c]
    tareas = [(c, a, m, s) for c in locs for a, m in meses(desde, hasta) for s in SECTORES
              if f"{a}-{m:02d}|{s}" not in cache[c]["consultas"]]
    print(f"Consultas pendientes: {len(tareas)}")

    fallos, inicio = 0, time.time()
    with ThreadPoolExecutor(HILOS) as pool:
        futuros = {pool.submit(consultar, locs[c], a, m, s): (c, a, m, s) for c, a, m, s in tareas}
        for i, fut in enumerate(as_completed(futuros), 1):
            c, a, m, s = futuros[fut]
            r = fut.result()
            if r is None:
                fallos += 1                       # se reintentará en la próxima ejecución
                continue
            with candado:
                cache[c]["consultas"][f"{a}-{m:02d}|{s}"] = r
                guardar_json(cache[c])
            if i % 50 == 0:
                ritmo = i / (time.time() - inicio)
                print(f"  {i}/{len(tareas)}  (~{(len(tareas) - i) / ritmo / 60:.0f} min restantes)")
    if fallos:
        print(f"Aviso: {fallos} consultas fallidas; vuelve a lanzar el script para completarlas")
    return fallos


def unir_csv(nombres):
    """Paso 2: junta todos los JSON de Datadis en un único CSV. Devuelve las rutas leídas."""
    rutas = sorted(glob.glob(PATRON_JSON.format("*")))
    filas = []
    for ruta in rutas:
        with open(ruta, encoding="utf-8") as f:
            datos = json.load(f)
        cod = datos["codigo_ine"]
        for clave, r in datos["consultas"].items():
            periodo, sector = clave.split("|")
            anio, mes = periodo.split("-")
            filas.append([cod, datos.get("municipio", nombres.get(cod, "")), int(anio), int(mes),
                          sector, r["energia_kwh"], r["contratos"]])
    filas.sort(key=lambda f: (f[0], f[2], f[3], f[4]))
    with open(RUTA_SALIDA, "w", newline="", encoding="utf-8") as f:
        escritor = csv.writer(f)
        escritor.writerow(COLUMNAS)
        escritor.writerows(filas)
    print(f"CSV: {len(filas)} filas de {len(rutas)} municipios -> {RUTA_SALIDA}")
    return rutas


def main():
    hoy = date.today()
    mes_pasado = (hoy.year, hoy.month - 1) if hoy.month > 1 else (hoy.year - 1, 12)
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--desde", default="2022-01", help="AAAA-MM (Datadis empieza en 2022)")
    parser.add_argument("--hasta", default=f"{mes_pasado[0]}-{mes_pasado[1]:02d}", help="AAAA-MM")
    parser.add_argument("--solo-csv", action="store_true", help="no descarga, solo une los JSON")
    parser.add_argument("--conservar-json", action="store_true", help="no borra los JSON al terminar")
    args = parser.parse_args()

    muni = pd.read_csv(RUTA_MUNICIPIOS, dtype={"codigo_ine": str}, encoding="utf-8")
    nombres = dict(zip(muni["codigo_ine"].str.zfill(5), muni["municipio"]))

    fallos = 0
    if not args.solo_csv:
        desde = tuple(int(x) for x in args.desde.split("-"))
        hasta = tuple(int(x) for x in args.hasta.split("-"))
        fallos = descargar(nombres, desde, hasta)

    rutas = unir_csv(nombres)
    # Los JSON solo se borran si la descarga quedó completa (si no, hacen falta para seguir)
    if rutas and not fallos and not args.conservar_json:
        for ruta in rutas:
            os.remove(ruta)
        print(f"Borrados {len(rutas)} JSON de {CARPETA}")


if __name__ == "__main__":
    main()
