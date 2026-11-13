
import time
from pathlib import Path

import pandas as pd
import requests

RAIZ = Path(__file__).resolve().parents[1]
RUTA_SALIDA = RAIZ / "data" / "raw" / "energia" / "ree_precios_horarios.csv"

URL = "https://apidatos.ree.es/es/datos/mercados/precios-mercados-tiempo-real"
FECHA_INICIO = "2016-01-01"
FECHA_FIN = None            # None = hasta ayer
PAUSA_S = 0.5               # entre peticiones, para no saturar la API
REINTENTOS = 3


def descargar_mes(sesion, inicio, fin):
    """Una petición (máx. un mes de datos horarios) -> lista de filas."""
    params = {"start_date": f"{inicio:%Y-%m-%d}T00:00",
              "end_date": f"{fin:%Y-%m-%d}T23:59",
              "time_trunc": "hour"}
    for intento in range(1, REINTENTOS + 1):
        try:
            r = sesion.get(URL, params=params, timeout=60)
            r.raise_for_status()
            filas = []
            for serie in r.json().get("included", []):
                nombre = serie["attributes"]["title"]
                for v in serie["attributes"]["values"]:
                    filas.append({"datetime": v["datetime"], "serie": nombre,
                                  "precio_eur_mwh": v["value"]})
            return filas
        except (requests.RequestException, ValueError, KeyError) as e:
            print(f"  intento {intento} fallido ({inicio:%Y-%m}): {e}")
            time.sleep(2 * intento)
    print(f"AVISO: sin datos para {inicio:%Y-%m}")
    return []


def main():
    fin_total = pd.Timestamp(FECHA_FIN) if FECHA_FIN else pd.Timestamp.today().normalize() - pd.Timedelta(days=1)
    sesion = requests.Session()
    sesion.headers["User-Agent"] = "proyecto-datos/1.0"

    filas = []
    for inicio in pd.date_range(FECHA_INICIO, fin_total, freq="MS"):
        fin = min(inicio + pd.offsets.MonthEnd(0), fin_total)
        bloque = descargar_mes(sesion, inicio, fin)
        print(f"{inicio:%Y-%m}: {len(bloque)} valores")
        filas.extend(bloque)
        time.sleep(PAUSA_S)

    df = pd.DataFrame(filas).drop_duplicates(subset=["datetime", "serie"])
    RUTA_SALIDA.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(RUTA_SALIDA, index=False, encoding="utf-8")
    print(f"\nGuardado {RUTA_SALIDA.relative_to(RAIZ)} ({len(df)} filas, "
          f"series: {sorted(df['serie'].unique())})")


if __name__ == "__main__":
    main()
