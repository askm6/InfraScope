
import re
import sys
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]
DIR_AEMET = RAIZ / "data" / "raw" / "aemet"
RUTA_ASIGNACION = DIR_AEMET / "municipio_estacion.csv"
RUTA_MENSUAL = DIR_AEMET / "aemet_mensual.csv"
RUTA_SALIDA = RAIZ / "data" / "processed" / "clima.csv"
RUTA_EXTREMOS = RAIZ / "data" / "processed" / "clima_extremos.csv"

COL_CODIGO = "codigo_ine"
COL_NOMBRE = "municipio"

DIST_MAX_KM = 25      
MIN_ANIOS = 1        

# clima.csv: solo el resumen anual del último año de los datos (fecha "AAAA-13")
# clima_extremos.csv: años con |z-score| >= UMBRAL_Z respecto a la referencia
ANIO_REF_DESDE, ANIO_REF_HASTA = 2016, 2025
VARIABLES_EXTREMOS = ["tm_mes", "ta_max", "ta_min", "nt_30"]
UMBRAL_Z = 1.5

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
    for col in ["tm_mes", "ta_max", "ta_min", "hr", "nt_30", "w_med"]:
        df[col] = df[col].map(a_numero) if col in df else float("nan")
    return df.drop_duplicates("anio")


def calcular_extremos(anuales):
    """Años con subida o bajada extrema (|z| >= UMBRAL_Z) de cada variable por municipio."""
    ref = anuales[anuales["anio"].between(ANIO_REF_DESDE, ANIO_REF_HASTA)]
    largo = ref.melt(id_vars=[COL_CODIGO, COL_NOMBRE, "anio"], value_vars=VARIABLES_EXTREMOS,
                     var_name="variable", value_name="valor").dropna(subset=["valor"])
    grupo = largo.groupby([COL_CODIGO, "variable"])["valor"]
    largo["media_municipio"] = grupo.transform("mean")
    desviacion = grupo.transform("std")
    largo["anomalia"] = largo["valor"] - largo["media_municipio"]
    largo["z_score"] = largo["anomalia"] / desviacion.where(desviacion > 0)
    extremos = largo[largo["z_score"].abs() >= UMBRAL_Z].copy()
    extremos["tipo"] = extremos["z_score"].map(lambda z: "subida" if z > 0 else "bajada")
    for col in ["media_municipio", "anomalia"]:
        extremos[col] = extremos[col].round(2)
    extremos["z_score"] = extremos["z_score"].round(2)
    columnas = [COL_CODIGO, COL_NOMBRE, "anio", "variable", "valor",
                "media_municipio", "anomalia", "z_score", "tipo"]
    return extremos[columnas].sort_values([COL_CODIGO, "anio", "variable"]).reset_index(drop=True)


def main():
    if not RUTA_ASIGNACION.exists():
        sys.exit(f"ERROR: no existe {RUTA_ASIGNACION}. Ejecuta antes src/aemet_descarga.py")
    asignacion = pd.read_csv(RUTA_ASIGNACION, dtype={COL_CODIGO: str}, encoding="utf-8-sig")
    mensual = pd.read_csv(RUTA_MENSUAL, dtype=str, encoding="utf-8-sig")

    filas = []
    todos = []
    for _, a in asignacion.iterrows():
        anual = leer_anuales(mensual, a[COL_CODIGO])
        if anual.empty:
            print(f"AVISO: {a[COL_NOMBRE]} sin resúmenes anuales")
            continue
        todos.append(anual.assign(**{COL_NOMBRE: a[COL_NOMBRE]}))
    anio_clima = max(int(t["anio"].max()) for t in todos)

    for _, a in asignacion.iterrows():
        anual = leer_anuales(mensual, a[COL_CODIGO])
        anual = anual[anual["anio"] == anio_clima] if not anual.empty else anual
        if anual.empty:
            print(f"AVISO: {a[COL_NOMBRE]} sin resumen anual de {anio_clima}")
            continue
        filas.append({
            COL_CODIGO: a[COL_CODIGO],
            COL_NOMBRE: a[COL_NOMBRE],
            "anio": anio_clima,
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
    print(f"Guardado {RUTA_SALIDA.relative_to(RAIZ)} ({len(clima)} municipios, año {anio_clima})")

    extremos = calcular_extremos(pd.concat(todos, ignore_index=True))
    extremos.to_csv(RUTA_EXTREMOS, index=False, encoding="utf-8-sig")
    print(f"Guardado {RUTA_EXTREMOS.relative_to(RAIZ)} ({len(extremos)} años extremos, "
          f"referencia {ANIO_REF_DESDE}-{ANIO_REF_HASTA}, |z| >= {UMBRAL_Z})\n")

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
