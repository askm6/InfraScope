"""Descarga de REE la demanda y la generación (renovable / no renovable) mensual
de cada comunidad autónoma. Guarda dos CSV en data/raw/energia/."""
import time
from pathlib import Path

import pandas as pd
import requests

RAIZ = Path(__file__).resolve().parents[1]
CARPETA_SALIDA = RAIZ / "data" / "raw" / "energia"
RUTA_DEMANDA = CARPETA_SALIDA / "ree_demanda_ccaa_mensual.csv"
RUTA_GENERACION = CARPETA_SALIDA / "ree_generacion_renovable_ccaa_mensual.csv"

URL_DEMANDA = "https://apidatos.ree.es/es/datos/demanda/evolucion"
URL_GENERACION = "https://apidatos.ree.es/es/datos/generacion/evolucion-renovable-no-renovable"
ANIO_INICIO = 2016
ANIO_FIN = None             # None = hasta el año en curso
PAUSA_S = 0.5               # entre peticiones, para no saturar la API
REINTENTOS = 3

# Identificadores de REE (los mismos que en ree_demanda_ccaa_anual.csv)
CCAA = {
    4: "Andalucia", 5: "Aragon", 6: "Cantabria", 7: "Castilla-La Mancha",
    8: "Castilla y Leon", 9: "Cataluna", 10: "Pais Vasco", 11: "Asturias",
    13: "Madrid", 14: "Navarra", 15: "Comunitat Valenciana", 16: "Extremadura",
    17: "Galicia", 20: "La Rioja", 21: "Murcia", 8742: "Canarias", 8743: "Illes Balears",
}
# Las islas dan error 502 con geo_limit=ccaa: hay que pedirlas como sistema eléctrico
GEO_LIMIT = {8742: "canarias", 8743: "baleares"}


def descargar_anio(sesion, url, ccaa_id, anio):
    """Una petición (un año, datos mensuales) -> lista de (serie, 'AAAA-MM', valor)."""
    params = {"start_date": f"{anio}-01-01T00:00", "end_date": f"{anio}-12-31T23:59",
              "time_trunc": "month", "geo_trunc": "electric_system",
              "geo_limit": GEO_LIMIT.get(ccaa_id, "ccaa"), "geo_ids": ccaa_id}
    for intento in range(1, REINTENTOS + 1):
        try:
            r = sesion.get(url, params=params, timeout=60)
            r.raise_for_status()
            filas = []
            for serie in r.json().get("included", []):
                nombre = serie["attributes"]["title"]
                for v in serie["attributes"]["values"]:
                    # "2025-03-01T00:00:00.000+01:00" -> "2025-03" (sin líos de zona horaria)
                    filas.append((nombre, v["datetime"][:7], v["value"]))
            return filas
        except (requests.RequestException, ValueError, KeyError) as e:
            print(f"  intento {intento} fallido ({ccaa_id}, {anio}): {e}")
            time.sleep(2 * intento)
    print(f"AVISO: sin datos para {CCAA[ccaa_id]} {anio}")
    return []


def main():
    anio_fin = ANIO_FIN or pd.Timestamp.today().year
    sesion = requests.Session()
    sesion.headers["User-Agent"] = "proyecto-datos/1.0"

    demanda, generacion = [], []
    for ccaa_id, nombre in CCAA.items():
        for anio in range(ANIO_INICIO, anio_fin + 1):
            for serie, mes, valor in descargar_anio(sesion, URL_DEMANDA, ccaa_id, anio):
                if serie == "Demanda":
                    demanda.append({"ccaa_id": ccaa_id, "ccaa": nombre, "anio": int(mes[:4]),
                                    "mes": int(mes[5:]), "demanda_mwh": valor})
            time.sleep(PAUSA_S)
            for serie, mes, valor in descargar_anio(sesion, URL_GENERACION, ccaa_id, anio):
                generacion.append({"ccaa_id": ccaa_id, "ccaa": nombre, "anio": int(mes[:4]),
                                   "mes": int(mes[5:]), "tipo": serie, "generacion_mwh": valor})
            time.sleep(PAUSA_S)
        print(f"{nombre}: {sum(f['ccaa_id'] == ccaa_id for f in demanda)} meses de demanda")

    CARPETA_SALIDA.mkdir(parents=True, exist_ok=True)
    df_dem = pd.DataFrame(demanda).drop_duplicates(subset=["ccaa_id", "anio", "mes"])
    df_gen = pd.DataFrame(generacion).drop_duplicates(subset=["ccaa_id", "anio", "mes", "tipo"])
    df_dem.to_csv(RUTA_DEMANDA, index=False, encoding="utf-8")
    df_gen.to_csv(RUTA_GENERACION, index=False, encoding="utf-8")
    print(f"\nGuardado {RUTA_DEMANDA.relative_to(RAIZ)} ({len(df_dem)} filas) y "
          f"{RUTA_GENERACION.relative_to(RAIZ)} ({len(df_gen)} filas)")


if __name__ == "__main__":
    main()
