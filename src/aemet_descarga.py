"""Descarga de datos climáticos de AEMET OpenData por municipio.

1. Descarga el inventario de estaciones climatológicas.
2. Asigna a cada municipio la estación más cercana (Haversine) que tenga datos.
3. Descarga los valores climatológicos mensuales/anuales 2016-2025
   en tramos de 3 años (máximo que permite la API).

Resultados (CSV, separador coma, UTF-8 con BOM, igual que el resto del proyecto):
  data/raw/aemet/estaciones.csv          inventario de estaciones
  data/raw/aemet/municipio_estacion.csv  estación asignada a cada municipio
  data/raw/aemet/aemet_mensual.csv       valores mensuales/anuales por municipio

Las respuestas de la API se guardan además como JSON (caché) en
data/raw/aemet/: si ya existen no se vuelven a descargar, así que el script se
puede relanzar si se corta a medias.

Uso:  python src/aemet_descarga.py
Requiere AEMET_API_KEY en el archivo .env de la raíz del proyecto.
"""

import json
import math
import os
import sys
import time
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parents[1]
RUTA_MUNICIPIOS = RAIZ / "data" / "processed" / "municipios.csv"
DIR_AEMET = RAIZ / "data" / "raw" / "aemet"

# Nombres de columnas de la tabla de municipios
COL_CODIGO = "codigo_ine"
COL_NOMBRE = "municipio"
COL_LAT = "latitud"
COL_LON = "longitud"

BASE_URL = "https://opendata.aemet.es/opendata/api"
ANIO_INI, ANIO_FIN = 2016, 2025
TRAMO_ANIOS = 3          # máximo permitido por la API
MAX_CANDIDATAS = 5       # estaciones cercanas a probar si la primera no tiene datos
PAUSA = 1.5              # segundos entre peticiones (la API limita ~50/min)
CSV_ENCODING = "utf-8-sig"  # mismo formato que el resto de CSV del proyecto


# ---------------------------------------------------------------- utilidades
def haversine_km(lat1, lon1, lat2, lon2):
    """Distancia en km entre dos puntos (lat/lon en grados)."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def coord_aemet_a_decimal(valor):
    """Convierte '394924N' / '0025309W' (GGMMSS + hemisferio) a grados decimales."""
    valor = str(valor).strip()
    hemisferio, digitos = valor[-1].upper(), valor[:-1]
    grados = int(digitos[:-4])
    minutos = int(digitos[-4:-2])
    segundos = int(digitos[-2:])
    dec = grados + minutos / 60 + segundos / 3600
    return -dec if hemisferio in ("S", "W") else dec


def decodificar(contenido):
    """AEMET a veces sirve UTF-8 y a veces ISO-8859-15."""
    try:
        return json.loads(contenido.decode("utf-8"))
    except UnicodeDecodeError:
        return json.loads(contenido.decode("iso-8859-15"))


# ---------------------------------------------------------------- API AEMET
def crear_sesion():
    load_dotenv(RAIZ / ".env")
    api_key = os.getenv("AEMET_API_KEY", "").strip()
    if not api_key:
        sys.exit(
            "ERROR: falta la API key. Abre el archivo .env de la raíz del proyecto "
            "y escribe tu clave después de AEMET_API_KEY="
        )
    sesion = requests.Session()
    sesion.headers.update({"api_key": api_key, "cache-control": "no-cache"})
    return sesion


def pedir_aemet(sesion, endpoint, reintentos=5):
    """Petición en dos pasos: la API devuelve una URL 'datos' que hay que descargar.

    Devuelve la lista de registros, o None si AEMET no tiene datos (404).
    """
    url = f"{BASE_URL}/{endpoint}"
    for intento in range(1, reintentos + 1):
        try:
            r = sesion.get(url, timeout=60)
            if r.status_code == 401:
                sys.exit("ERROR 401: la API key no es válida. Revisa el archivo .env.")
            if r.status_code == 429:
                print("   Límite de peticiones alcanzado, espero 60 s...")
                time.sleep(60)
                continue
            r.raise_for_status()
            meta = decodificar(r.content)
            estado = int(meta.get("estado", 0))
            if estado == 404:
                return None
            if estado == 429:
                print("   Límite de peticiones alcanzado, espero 60 s...")
                time.sleep(60)
                continue
            if estado != 200:
                raise RuntimeError(f"estado {estado}: {meta.get('descripcion')}")

            time.sleep(PAUSA)
            r2 = sesion.get(meta["datos"], timeout=120)
            r2.raise_for_status()
            time.sleep(PAUSA)
            return decodificar(r2.content)
        except (requests.RequestException, ValueError, RuntimeError) as e:
            espera = 10 * intento
            print(f"   Intento {intento}/{reintentos} fallido ({e}). Reintento en {espera} s")
            time.sleep(espera)
    raise RuntimeError(f"No se pudo descargar {endpoint} tras {reintentos} intentos")


def cargar_o_descargar(sesion, endpoint, ruta):
    """Usa el JSON guardado si existe; si no, lo descarga y lo guarda.

    Si AEMET no tiene datos se guarda una lista vacía para no repetir la petición.
    """
    if ruta.exists():
        return json.loads(ruta.read_text(encoding="utf-8"))
    datos = pedir_aemet(sesion, endpoint) or []
    ruta.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")
    return datos


# ---------------------------------------------------------------- pasos
def descargar_estaciones(sesion):
    endpoint = "valores/climatologicos/inventarioestaciones/todasestaciones"
    datos = cargar_o_descargar(sesion, endpoint, DIR_AEMET / "estaciones.json")
    est = pd.DataFrame(datos)
    est["lat"] = est["latitud"].map(coord_aemet_a_decimal)
    est["lon"] = est["longitud"].map(coord_aemet_a_decimal)
    est["altitud"] = pd.to_numeric(est["altitud"], errors="coerce")
    est.to_csv(DIR_AEMET / "estaciones.csv", index=False, encoding=CSV_ENCODING)
    return est


def tramos():
    for ini in range(ANIO_INI, ANIO_FIN + 1, TRAMO_ANIOS):
        yield ini, min(ini + TRAMO_ANIOS - 1, ANIO_FIN)


def descargar_estacion(sesion, indicativo):
    """Descarga todos los tramos de una estación.

    Devuelve (registros, nº de años con resumen anual).
    """
    registros, anios = [], set()
    for ini, fin in tramos():
        endpoint = (
            f"valores/climatologicos/mensualesanuales/datos/"
            f"anioini/{ini}/aniofin/{fin}/estacion/{indicativo}"
        )
        ruta = DIR_AEMET / f"mensuales_{indicativo}_{ini}_{fin}.json"
        for reg in cargar_o_descargar(sesion, endpoint, ruta):
            registros.append(reg)
            if str(reg.get("fecha", "")).endswith("-13") and reg.get("tm_mes"):
                anios.add(reg["fecha"][:4])
    return registros, len(anios)


def main():
    DIR_AEMET.mkdir(parents=True, exist_ok=True)
    if not RUTA_MUNICIPIOS.exists():
        sys.exit(f"ERROR: no encuentro la tabla de municipios en {RUTA_MUNICIPIOS}")
    municipios = pd.read_csv(RUTA_MUNICIPIOS, dtype={COL_CODIGO: str})

    sesion = crear_sesion()
    estaciones = descargar_estaciones(sesion)

    print(f"Descargando datos de AEMET para {len(municipios)} municipios (tarda unos minutos)...")
    filas, mensual = [], []
    for _, m in municipios.iterrows():
        dist = estaciones.apply(
            lambda e: haversine_km(m[COL_LAT], m[COL_LON], e["lat"], e["lon"]), axis=1
        )
        candidatas = estaciones.assign(distancia_km=dist).nsmallest(MAX_CANDIDATAS, "distancia_km")

        elegida = None
        for _, e in candidatas.iterrows():
            registros, n_anios = descargar_estacion(sesion, e["indicativo"])
            if n_anios > 0:
                elegida = e
                break

        if elegida is None:
            print(f"AVISO: {m[COL_NOMBRE]} sin datos en sus {MAX_CANDIDATAS} estaciones más cercanas")
            continue
        for reg in registros:
            mensual.append({COL_CODIGO: m[COL_CODIGO], COL_NOMBRE: m[COL_NOMBRE], **reg})
        filas.append({
            COL_CODIGO: m[COL_CODIGO],
            COL_NOMBRE: m[COL_NOMBRE],
            "indicativo": elegida["indicativo"],
            "estacion": elegida["nombre"],
            "distancia_km": round(elegida["distancia_km"], 2),
            "altitud_estacion": elegida["altitud"],
            "n_anios_con_datos": n_anios,
        })

    pd.DataFrame(filas).to_csv(
        DIR_AEMET / "municipio_estacion.csv", index=False, encoding=CSV_ENCODING
    )
    pd.DataFrame(mensual).to_csv(
        DIR_AEMET / "aemet_mensual.csv", index=False, encoding=CSV_ENCODING
    )
    print(f"Hecho: {len(filas)} municipios. CSV guardados en data/raw/aemet/")


if __name__ == "__main__":
    main()
