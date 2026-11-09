"""Limpieza de los datos de AEMET y cálculo de indicadores climáticos por municipio.

Lee los JSON descargados por aemet_descarga.py, se queda con los resúmenes
anuales (fecha "AAAA-13") y calcula, por municipio (media 2016-2025):

  tm_media      temperatura media anual (ºC)            <- tm_mes
  ta_max_hist   temperatura máxima absoluta (ºC)        <- ta_max (máximo del periodo)
  hr_media      humedad relativa media (%)              <- hr
  dias_calor_30 días al año con máxima >= 30 ºC         <- nt_30
  w_med         velocidad media del viento              <- w_med

Genera data/processed/clima.csv.

Uso:  python src/aemet_limpieza.py
"""

import re
import sys
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]
DIR_AEMET = RAIZ / "data" / "raw" / "aemet"
RUTA_ASIGNACION = DIR_AEMET / "municipio_estacion.csv"
RUTA_MENSUAL = DIR_AEMET / "aemet_mensual.csv"
RUTA_SALIDA = RAIZ / "data" / "processed" / "clima.csv"

COL_CODIGO = "codigo_ine"
COL_NOMBRE = "municipio"

DIST_MAX_KM = 25      # estaciones más lejanas se marcan como dudosas
MIN_ANIOS = 7         # menos años de datos se marca como dudoso

_NUMERO = re.compile(r"-?\d+(?:\.\d+)?")


def a_numero(valor):
    """'38.4(15/jul)' -> 38.4 ; '12.3' -> 12.3 ; vacío -> NaN."""
    if valor is None:
        return float("nan")
    m = _NUMERO.search(str(valor))
    return float(m.group()) if m else float("nan")


def leer_anuales(mensual, codigo):
    df = mensual[mensual[COL_CODIGO] == codigo]
    if df.empty:
        return pd.DataFrame()
    df = df[df["fecha"].astype(str).str.endswith("-13")].copy()
    df["anio"] = df["fecha"].str[:4].astype(int)
    for col in ["tm_mes", "ta_max", "hr", "nt_30", "w_med"]:
        df[col] = df[col].map(a_numero) if col in df else float("nan")
    return df.drop_duplicates("anio")


def main():
    if not RUTA_ASIGNACION.exists():
        sys.exit(f"ERROR: no existe {RUTA_ASIGNACION}. Ejecuta antes src/aemet_descarga.py")
    asignacion = pd.read_csv(RUTA_ASIGNACION, dtype={COL_CODIGO: str}, encoding="utf-8-sig")
    mensual = pd.read_csv(RUTA_MENSUAL, dtype=str, encoding="utf-8-sig")

    filas = []
    for _, a in asignacion.iterrows():
        anual = leer_anuales(mensual, a[COL_CODIGO])
        if anual.empty:
            print(f"AVISO: {a[COL_NOMBRE]} sin resúmenes anuales")
            continue
        filas.append({
            COL_CODIGO: a[COL_CODIGO],
            COL_NOMBRE: a[COL_NOMBRE],
            "indicativo": a["indicativo"],
            "estacion": a["estacion"],
            "distancia_km": a["distancia_km"],
            "altitud_estacion": a["altitud_estacion"],
            "n_anios": int(anual["tm_mes"].notna().sum()),
            "tm_media": round(anual["tm_mes"].mean(), 2),
            "ta_max_hist": anual["ta_max"].max(),
            "hr_media": round(anual["hr"].mean(), 1),
            "dias_calor_30": round(anual["nt_30"].mean(), 1),
            "w_med": round(anual["w_med"].mean(), 1),
        })

    clima = pd.DataFrame(filas)
    clima["dato_dudoso"] = (clima["distancia_km"] > DIST_MAX_KM) | (clima["n_anios"] < MIN_ANIOS)
    RUTA_SALIDA.parent.mkdir(parents=True, exist_ok=True)
    clima.to_csv(RUTA_SALIDA, index=False, encoding="utf-8-sig")
    print(f"Guardado {RUTA_SALIDA.relative_to(RAIZ)} ({len(clima)} municipios)\n")

    # ---- comprobaciones rápidas
    columnas = [COL_NOMBRE, "estacion", "distancia_km", "n_anios",
                "tm_media", "dias_calor_30", "hr_media"]
    print(clima.sort_values("dias_calor_30", ascending=False)[columnas].to_string(index=False))

    dudosos = clima[clima["dato_dudoso"]]
    if not dudosos.empty:
        print(f"\nAVISO: estaciones a más de {DIST_MAX_KM} km o con menos de {MIN_ANIOS} años:")
        print(dudosos[[COL_NOMBRE, "estacion", "distancia_km", "n_anios"]].to_string(index=False))

    por_nombre = clima.set_index(COL_NOMBRE)["dias_calor_30"]
    if {"Sevilla", "Bilbao"} <= set(por_nombre.index):
        ok = por_nombre["Sevilla"] > por_nombre["Bilbao"]
        print(f"\nComprobación Sevilla ({por_nombre['Sevilla']}) > Bilbao "
              f"({por_nombre['Bilbao']}) días de calor: {'OK' if ok else 'REVISAR'}")


if __name__ == "__main__":
    main()
