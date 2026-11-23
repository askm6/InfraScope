"""Descarga los datos de origen de socioeconomico.py para TODOS los municipios de España y
sustituye los CSV del INE de data/raw/socioeconomico/ (mismo formato que tenían).
El paro registrado del SEPE se descarga aparte, con paro_descarga.py.

  - ine_renta_media_municipios.csv: Atlas de Distribución de Renta de los Hogares (ADRH)
    del INE, renta neta media por persona y por hogar (cod_ine, municipio, indicador,
    anio, valor_eur).
  - ine_indicadores_demograficos_municipios.csv: ADRH, indicadores demográficos
    (cod_ine, municipio, indicador, anio, valor).

El ADRH se publica en una tabla por provincia (con municipios, distritos y secciones
censales). Se descarga provincia a provincia porque el servidor del INE corta a menudo las
descargas grandes y no permite continuarlas; de cada tabla solo se guardan las filas de
municipio.

Uso: python src/socioeconomico_descarga.py   (o python run_pipeline.py --solo socioeconomico_descarga)
Tarda unos minutos.
"""
import io
import time
from pathlib import Path

import pandas as pd
import requests

RAIZ = Path(__file__).resolve().parents[1]
CARPETA = RAIZ / "data" / "raw" / "socioeconomico"
RUTA_RENTA = CARPETA / "ine_renta_media_municipios.csv"
RUTA_DEMOGRAFIA = CARPETA / "ine_indicadores_demograficos_municipios.csv"

CABECERA_HTTP = {"User-Agent": "Proyecto3-datos/1.0 (proyecto academico)"}
REINTENTOS = 5

# INE (operación 353, ADRH): nombre de las tablas y tablas nacionales que se saltan
# porque repiten lo mismo que las provinciales en un único archivo de cientos de MB
URL_INE_TABLAS = "https://servicios.ine.es/wstempus/js/ES/TABLAS_OPERACION/353"
URL_INE_CSV = "https://www.ine.es/jaxiT3/files/t/es/csv_bdsc/{id}.csv"
TABLA_RENTA = "Indicadores de renta media y mediana"
TABLA_DEMOGRAFIA = "Indicadores demográficos"
TABLAS_NACIONALES = {30824, 30832}
INDICADORES_RENTA = ["Renta neta media por persona", "Renta neta media por hogar"]
INDICADORES_DEMOGRAFIA = ["Edad media de la población", "Porcentaje de población de 65 y más años",
                          "Porcentaje de población menor de 18 años", "Tamaño medio del hogar"]


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


def texto(contenido):
    """Los CSV del INE vienen a veces en UTF-8 y a veces en Latin-1."""
    try:
        return contenido.decode("utf-8-sig")
    except UnicodeDecodeError:
        return contenido.decode("latin-1")


def numero_es(serie):
    """'3.034' -> 3034 y '40,8' -> 40.8 (formato español). '.', '..' o vacío -> NaN."""
    s = serie.astype(str).str.strip().str.replace(".", "", regex=False).str.replace(",", ".", regex=False)
    return pd.to_numeric(s, errors="coerce")


# ---------------- ADRH (INE) ----------------
def tablas_ine(sesion, nombre):
    """Identificadores de las tablas provinciales del ADRH con ese nombre."""
    tablas = sesion.get(URL_INE_TABLAS, timeout=120).json()
    return [t["Id"] for t in tablas if t["Nombre"] == nombre and t["Id"] not in TABLAS_NACIONALES]


def filas_municipio(sesion, id_tabla, indicadores):
    """Filas de municipio (sin distrito ni sección) de una tabla del ADRH. Devuelve None si
    la tabla no es municipal (hay tablas con totales de España, comunidades y provincias)."""
    df = pd.read_csv(io.StringIO(texto(descargar(sesion, URL_INE_CSV.format(id=id_tabla)))),
                     sep=";", dtype=str)
    if not {"Municipios", "Distritos", "Secciones"} <= set(df.columns):
        return None
    col_indicador = df.columns[3]           # "Indicadores de renta media..." / "Indicadores demográficos"
    df = df[df["Distritos"].isna() & df["Secciones"].isna() & df[col_indicador].isin(indicadores)]
    partes = df["Municipios"].str.strip().str.split(" ", n=1, expand=True)
    return pd.DataFrame({"cod_ine": partes[0], "municipio": partes[1],
                         "indicador": df[col_indicador].values,
                         "anio": pd.to_numeric(df["Periodo"], errors="coerce").astype("Int64").values,
                         "valor": numero_es(df["Total"]).values})


def descargar_adrh(sesion, nombre_tabla, indicadores):
    """Todas las tablas provinciales de un tipo, unidas (una fila por municipio,
    indicador y año)."""
    ids = tablas_ine(sesion, nombre_tabla)
    partes = []
    for n, id_tabla in enumerate(ids, 1):
        filas = filas_municipio(sesion, id_tabla, indicadores)
        if filas is None:
            print(f"  {nombre_tabla}: tabla {n}/{len(ids)} ({id_tabla}) no es municipal, se salta")
            continue
        partes.append(filas)
        print(f"  {nombre_tabla}: tabla {n}/{len(ids)} ({id_tabla})", flush=True)
    df = pd.concat(partes, ignore_index=True).drop_duplicates(["cod_ine", "indicador", "anio"])
    df = df[df["cod_ine"].str.fullmatch(r"\d{5}")]
    return df.sort_values(["cod_ine", "indicador", "anio"]).reset_index(drop=True)


def main():
    inicio = time.time()
    CARPETA.mkdir(parents=True, exist_ok=True)
    with requests.Session() as sesion:
        sesion.headers.update(CABECERA_HTTP)

        print("Renta media (INE, ADRH)...", flush=True)
        renta = descargar_adrh(sesion, TABLA_RENTA, INDICADORES_RENTA)
        print("Indicadores demográficos (INE, ADRH)...", flush=True)
        demografia = descargar_adrh(sesion, TABLA_DEMOGRAFIA, INDICADORES_DEMOGRAFIA)

    # Se escribe al final, para no dejar archivos a medias si algo falla
    renta["valor"] = renta["valor"].round().astype("Int64")
    renta.rename(columns={"valor": "valor_eur"}).to_csv(RUTA_RENTA, index=False, encoding="utf-8")
    demografia.to_csv(RUTA_DEMOGRAFIA, index=False, encoding="utf-8")

    for ruta, df in [(RUTA_RENTA, renta), (RUTA_DEMOGRAFIA, demografia)]:
        print(f"Guardado {ruta.relative_to(RAIZ)}: {len(df)} filas, "
              f"{df['cod_ine'].nunique()} municipios")
    print(f"Tiempo: {time.time() - inicio:.0f} s")


if __name__ == "__main__":
    main()
