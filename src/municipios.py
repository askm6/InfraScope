"""Genera la lista maestra de municipios: data/processed/municipios.csv.

Columnas: codigo_ine, municipio, latitud, longitud (una fila por municipio
de España). Casi todos los scripts de limpieza la leen para saber qué municipios hay.

Fuentes (se descargan a data/raw/municipios/ si no están):
  - INE, "Relación de municipios y sus códigos" (diccionarioAA.xlsx): códigos y nombres
    oficiales de todos los municipios.
  - Wikidata (consulta SPARQL): coordenadas de cada municipio, cruzadas por el código INE
    (propiedad P772). El IGN/CNIG no permite la descarga automática del Nomenclátor.

Uso: python src/municipios.py   (o python run_pipeline.py --solo municipios)
     Para forzar una descarga nueva, borra los archivos de data/raw/municipios/.
"""
import io
import re
from pathlib import Path

import pandas as pd
import requests

# ---------------- Configuración ----------------
CARPETA_RAW = Path("data/raw/municipios")
ANIO_DICCIONARIO = 26                                # diccionario26.xlsx = municipios a 1-1-2026
URL_INE = f"https://www.ine.es/daco/daco42/codmun/diccionario{ANIO_DICCIONARIO}.xlsx"
RUTA_INE = CARPETA_RAW / f"ine_diccionario{ANIO_DICCIONARIO}.xlsx"
URL_WIKIDATA = "https://query.wikidata.org/sparql"
RUTA_WIKIDATA = CARPETA_RAW / "wikidata_coordenadas_municipios.csv"
RUTA_SALIDA = Path("data/processed/municipios.csv")
CABECERA_HTTP = {"User-Agent": "Proyecto3-datos/1.0 (proyecto academico)"}

# Coordenadas de todos los elementos con código INE de municipio. Se marca si el elemento
# es un "municipio de España" (Q2074737) para descartar municipios desaparecidos o fusionados
CONSULTA_WIKIDATA = """
SELECT ?item ?ine ?coord ?es_municipio WHERE {
  ?item wdt:P772 ?ine .
  FILTER(STRLEN(?ine) = 5)
  OPTIONAL { ?item wdt:P625 ?coord }
  BIND(EXISTS { ?item wdt:P31 wd:Q2074737 } AS ?es_municipio)
}
"""

# Artículos que el INE pone al final ("Palmas de Gran Canaria, Las")
ARTICULOS = {"el", "la", "los", "las", "lo", "l'", "a", "o", "as", "os", "es", "sa", "ses",
             "s'", "els", "les", "en", "na"}


def descargar(url, ruta, **kwargs):
    """Descarga `url` a `ruta` solo si el archivo no existe todavía."""
    if ruta.exists():
        return
    ruta.parent.mkdir(parents=True, exist_ok=True)
    print(f"Descargando {url} ...")
    r = requests.get(url, headers=CABECERA_HTTP, timeout=300, **kwargs)
    r.raise_for_status()
    ruta.write_bytes(r.content)


def descargar_wikidata():
    """Consulta SPARQL de Wikidata -> CSV con item, ine, latitud, longitud, es_municipio."""
    if RUTA_WIKIDATA.exists():
        return
    print("Consultando Wikidata (coordenadas por código INE) ...")
    r = requests.get(URL_WIKIDATA, params={"query": CONSULTA_WIKIDATA, "format": "json"},
                     headers=CABECERA_HTTP, timeout=300)
    r.raise_for_status()
    filas = []
    for b in r.json()["results"]["bindings"]:
        lon = lat = None
        if "coord" in b:
            m = re.match(r"Point\(([-\d.eE]+) ([-\d.eE]+)\)", b["coord"]["value"])
            if m:
                lon, lat = float(m.group(1)), float(m.group(2))
        filas.append({"item": b["item"]["value"].rsplit("/", 1)[-1], "ine": b["ine"]["value"],
                      "latitud": lat, "longitud": lon,
                      "es_municipio": b["es_municipio"]["value"] == "true"})
    RUTA_WIKIDATA.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(filas).to_csv(RUTA_WIKIDATA, index=False, encoding="utf-8")


def nombre_natural(nombre):
    """'Palmas de Gran Canaria, Las' -> 'Las Palmas de Gran Canaria';
    'Hospitalet de Llobregat, L'' -> "L'Hospitalet de Llobregat". En los nombres
    bilingües ('Coruña, A/...') se trata cada parte por separado."""
    partes = []
    for parte in str(nombre).split("/"):
        parte = parte.strip()
        if ", " in parte:
            base, art = parte.rsplit(", ", 1)
            if art.lower() in ARTICULOS:
                parte = f"{art}{base}" if art.endswith("'") else f"{art} {base}"
        partes.append(parte)
    return "/".join(partes)


def cargar_ine():
    """Municipios oficiales del INE: codigo_ine (5 dígitos, texto) y municipio.
    El proyecto trabaja solo por municipio: no se guarda la provincia (si algún script la
    necesita por dentro, son las 2 primeras cifras del código INE)."""
    df = pd.read_excel(RUTA_INE, header=1, dtype=str)
    df = df.dropna(subset=["CPRO", "CMUN"])
    df["codigo_ine"] = df["CPRO"].str.strip().str.zfill(2) + df["CMUN"].str.strip().str.zfill(3)
    df["municipio"] = df["NOMBRE"].str.strip().map(nombre_natural)
    return df[["codigo_ine", "municipio"]].drop_duplicates("codigo_ine")


def cargar_coordenadas():
    """Una coordenada por código INE. Si Wikidata tiene varios elementos con el mismo
    código, se prefiere el que es 'municipio de España' y tiene coordenadas."""
    wd = pd.read_csv(RUTA_WIKIDATA, dtype={"ine": str, "item": str})
    wd = wd.dropna(subset=["latitud", "longitud"])
    wd["qid"] = wd["item"].str[1:].astype(int)
    # Preferencia: municipio actual primero; a igualdad, el elemento más antiguo (QID menor)
    wd = wd.sort_values(["ine", "es_municipio", "qid"], ascending=[True, False, True])
    wd = wd.drop_duplicates("ine")
    return wd.rename(columns={"ine": "codigo_ine"})[["codigo_ine", "latitud", "longitud"]]


def construir():
    """Cruza INE (lista oficial) con Wikidata (coordenadas) por codigo_ine."""
    municipios = cargar_ine()
    coords = cargar_coordenadas()
    df = municipios.merge(coords, on="codigo_ine", how="left")
    df["latitud"] = df["latitud"].round(4)
    df["longitud"] = df["longitud"].round(4)

    sin = df[df["latitud"].isna()]
    if len(sin):
        print(f"Aviso: {len(sin)} municipios sin coordenadas en Wikidata (quedan vacías):")
        print(sin.to_string(index=False))
    # Comprobación: coordenadas dentro de España
    fuera = ~(df["latitud"].between(27, 44.5) & df["longitud"].between(-18.5, 4.5))
    fuera &= df["latitud"].notna()
    if fuera.any():
        print(f"Aviso: coordenadas fuera de España (se vacían): {df.loc[fuera, 'codigo_ine'].tolist()}")
        df.loc[fuera, ["latitud", "longitud"]] = None
    return df.sort_values("codigo_ine").reset_index(drop=True)


if __name__ == "__main__":
    descargar(URL_INE, RUTA_INE)
    descargar_wikidata()
    resultado = construir()
    resultado.to_csv(RUTA_SALIDA, index=False, encoding="utf-8")
    print(f"{len(resultado)} municipios ({resultado['latitud'].notna().sum()} con coordenadas) "
          f"-> {RUTA_SALIDA}")
