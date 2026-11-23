"""Descarga del SEPE el paro registrado mensual de TODOS los municipios de España y lo
guarda, tal como se publica, en data/raw/socioeconomico/paro_municipios_sepe_mensual.csv.

El SEPE publica un CSV por año con una fila por mes y municipio. Cuando un municipio tiene
menos de 5 parados escribe "<5" (secreto estadístico); aquí se guarda ese texto sin tocar y
es paro.py quien decide cómo tratarlo.

Columnas: anio, mes, cod_ine, municipio, paro_registrado

Uso: python src/paro_descarga.py   (o python run_pipeline.py --solo paro_descarga)
Tarda alrededor de un minuto.
"""
import io
import time
from pathlib import Path

import pandas as pd
import requests

RAIZ = Path(__file__).resolve().parents[1]
RUTA_SALIDA = RAIZ / "data" / "raw" / "socioeconomico" / "paro_municipios_sepe_mensual.csv"

URL_SEPE = ("https://sede.sepe.gob.es/es/portaltrabaja/resources/sede/datos_abiertos/datos/"
            "Paro_por_municipios_{anio}_csv.csv")
ANIOS = range(2016, 2026)          # 2025 es el último año completo
CABECERA_HTTP = {"User-Agent": "Proyecto3-datos/1.0 (proyecto academico)"}
REINTENTOS = 5


def descargar(sesion, url):
    """Descarga una URL entera a memoria, con reintentos si se corta la conexión."""
    for intento in range(1, REINTENTOS + 1):
        try:
            r = sesion.get(url, timeout=300)
            r.raise_for_status()
            return r.content
        except requests.RequestException as e:
            print(f"    intento {intento}/{REINTENTOS} fallido ({type(e).__name__})", flush=True)
            time.sleep(3 * intento)
    raise RuntimeError(f"No se ha podido descargar {url}")


def columna(columnas, *inicios):
    """Primera columna cuyo nombre (en minúsculas) empieza por alguno de los textos."""
    return next(c for c in columnas if c.startswith(inicios))


def paro_anio(sesion, anio):
    """Un año del SEPE -> una fila por mes y municipio, con el paro como texto."""
    contenido = descargar(sesion, URL_SEPE.format(anio=anio))
    try:
        lineas = contenido.decode("utf-8-sig").splitlines()
    except UnicodeDecodeError:
        lineas = contenido.decode("latin-1").splitlines()      # el SEPE usa Latin-1
    # La primera línea es un título; la cabecera es la que contiene "Codigo Municipio"
    inicio = next(i for i, l in enumerate(lineas[:10])
                  if "codigo municipio" in l.lower() or "código municipio" in l.lower())
    df = pd.read_csv(io.StringIO("\n".join(lineas[inicio:])), sep=";", dtype=str)
    df.columns = [c.strip().lower() for c in df.columns]
    df = df.dropna(subset=[columna(df.columns, "codigo municipio", "código municipio")])
    mes = pd.to_numeric(df[columna(df.columns, "código mes", "codigo mes")], errors="coerce")
    res = pd.DataFrame({
        "anio": anio,
        "mes": (mes % 100).astype("Int64"),
        "cod_ine": df[columna(df.columns, "codigo municipio", "código municipio")].str.strip().str.zfill(5),
        "municipio": df["municipio"].str.strip(),
        "paro_registrado": df["total paro registrado"].str.strip(),
    })
    print(f"  {anio}: {res['cod_ine'].nunique()} municipios, {res['mes'].nunique()} meses, "
          f"{(res['paro_registrado'] == '<5').sum()} valores '<5'", flush=True)
    return res


def main():
    inicio = time.time()
    with requests.Session() as sesion:
        sesion.headers.update(CABECERA_HTTP)
        df = pd.concat([paro_anio(sesion, a) for a in ANIOS], ignore_index=True)
    RUTA_SALIDA.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(RUTA_SALIDA, index=False, encoding="utf-8")
    print(f"Guardado {RUTA_SALIDA.relative_to(RAIZ)}: {len(df)} filas, "
          f"{df['cod_ine'].nunique()} municipios ({time.time() - inicio:.0f} s)")


if __name__ == "__main__":
    main()
