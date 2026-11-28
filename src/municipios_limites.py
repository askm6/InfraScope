"""Superficie y tipo de cada recinto municipal: data/processed/municipios_limites.csv.

Fuente: IGN, «Líneas límite municipales» en formato INSPIRE
(data/raw/municipios/lineas_limite_gml.zip, archivo au_AdministrativeUnit_4thOrder0.gml).
Cada recinto trae su código nacional de 11 cifras (34 + comunidad + provincia + código INE
de 5 cifras), su nombre y su contorno en latitud/longitud (ETRS89).

El IGN tiene más recintos que municipios (8.220 frente a 8.132):
  - municipio:  recinto de un municipio (sus 5 últimas cifras son el código INE).
  - condominio: terreno compartido por varios municipios (código 53xxx, p. ej.
                «Comunidad de Los Ausines y Revilla del Campo»). No tiene código INE.
  - territorio: otros territorios sin municipio (código 54xxx). No tiene código INE.

La superficie se calcula sobre el elipsoide GRS80 (el de ETRS89) pasando cada punto a la
esfera de igual área («latitud autálica») y sumando el área bajo cada lado del contorno.
Se suman los trozos de cada recinto (exclaves) y se restan los huecos (enclaves).
Al terminar se compara con la superficie de Wikidata como comprobación.

Columnas: codigo_ign, codigo_ine, nombre, tipo_recinto, n_poligonos, superficie_km2.
La usa src/etl.py para añadir la superficie a la tabla única por municipio.

Uso: python src/municipios_limites.py   (o python run_pipeline.py --solo municipios_limites)
"""
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

# ---------------- Configuración ----------------
RUTA_ZIP = Path("data/raw/municipios/lineas_limite_gml.zip")
ARCHIVO_MUNICIPIOS = "au_AdministrativeUnit_4thOrder0.gml"     # 4thOrder = municipios
RUTA_MUNICIPIOS = Path("data/processed/municipios.csv")        # lista maestra (comprobación)
RUTA_WIKIDATA = Path("data/raw/poblacion/wikidata_superficie_municipios.csv")  # comprobación
RUTA_SALIDA = Path("data/processed/municipios_limites.csv")

NS = {
    "au": "http://inspire.ec.europa.eu/schemas/au/4.0",
    "gml": "http://www.opengis.net/gml/3.2",
    "gn": "http://inspire.ec.europa.eu/schemas/gn/4.0",
    "gmd": "http://www.isotc211.org/2005/gmd",
}
ETIQUETA_UNIDAD = f"{{{NS['au']}}}AdministrativeUnit"

# Tipos de recinto
MUNICIPIO, CONDOMINIO, TERRITORIO = "municipio", "condominio", "territorio"
PREFIJO_CONDOMINIO = "53"                # código de "provincia" que el IGN usa para condominios

# Elipsoide GRS80 (ETRS89)
SEMIEJE_MAYOR_M = 6_378_137.0
APLANAMIENTO = 1 / 298.257222101
DIFERENCIA_AVISO_PCT = 5                 # diferencia con Wikidata a partir de la que se avisa


# ---------------- Superficie ----------------

E2 = APLANAMIENTO * (2 - APLANAMIENTO)   # excentricidad al cuadrado
E = np.sqrt(E2)


def _q(seno_lat):
    """Función auxiliar de la latitud autálica (Snyder, «Map Projections», ec. 3-12)."""
    return (1 - E2) * (seno_lat / (1 - E2 * seno_lat ** 2)
                       - np.log((1 - E * seno_lat) / (1 + E * seno_lat)) / (2 * E))


Q_POLO = _q(1.0)
RADIO_AUTALICO_M = SEMIEJE_MAYOR_M * np.sqrt(Q_POLO / 2)   # esfera con la misma superficie


def seno_latitud_autalica(lat_grados):
    """Seno de la latitud en la esfera de igual área que el elipsoide."""
    return _q(np.sin(np.radians(lat_grados))) / Q_POLO


def area_anillo_km2(anillo):
    """Superficie (km²) encerrada por un anillo cerrado de puntos (lat, lon) en grados.
    Suma el área bajo cada lado (fórmula del trapecio sobre la esfera autálica); el sentido
    del anillo no importa."""
    anillo = np.asarray(anillo, dtype=float)
    seno = seno_latitud_autalica(anillo[:, 0])
    lon = np.radians(anillo[:, 1])
    suma = np.sum((lon[1:] - lon[:-1]) * (seno[1:] + seno[:-1]))
    return abs(suma) * RADIO_AUTALICO_M ** 2 / 2 / 1e6


def area_poligono_km2(exterior, interiores=()):
    """Superficie de un polígono: su contorno exterior menos sus huecos."""
    return area_anillo_km2(exterior) - sum(area_anillo_km2(h) for h in interiores)


# ---------------- Lectura del GML ----------------

def tipo_recinto(codigo_ign, nivel):
    """'municipio', 'condominio' o 'territorio' según el código y el nivel del IGN."""
    if nivel == "Territorio":
        return TERRITORIO
    if codigo_ign[-5:-3] == PREFIJO_CONDOMINIO:
        return CONDOMINIO
    return MUNICIPIO


def puntos(pos_list, contexto):
    """gml:posList 'lat lon lat lon ...' -> matriz N x 2 (lat, lon). Si trae altura
    (srsDimension="3"), se descarta. `contexto` identifica el recinto en los errores."""
    if pos_list is None or not (pos_list.text or "").strip():
        raise ValueError(f"{contexto}: polígono sin coordenadas")
    dimension = int(pos_list.get("srsDimension", 2))
    return np.array(pos_list.text.split(), dtype=float).reshape(-1, dimension)[:, :2]


def superficie_unidad(unidad, contexto):
    """(número de polígonos, superficie en km²) de una au:AdministrativeUnit."""
    poligonos = unidad.findall(".//gml:Polygon", NS)
    total = 0.0
    for poligono in poligonos:
        exterior = puntos(poligono.find("gml:exterior//gml:posList", NS), contexto)
        huecos = [puntos(h, contexto) for h in poligono.findall("gml:interior//gml:posList", NS)]
        total += area_poligono_km2(exterior, huecos)
    return len(poligonos), total


def describir_unidad(unidad):
    """Una fila de la tabla de salida a partir de una au:AdministrativeUnit."""
    codigo = (unidad.findtext("au:nationalCode", namespaces=NS) or "").strip()
    if len(codigo) != 11:
        raise ValueError(f"recinto {unidad.get(f'{{{NS['gml']}}}id')}: código nacional "
                         f"no válido ({codigo!r})")
    nivel = unidad.findtext("au:nationalLevelName/gmd:LocalisedCharacterString", namespaces=NS)
    tipo = tipo_recinto(codigo, nivel)
    n_poligonos, superficie = superficie_unidad(unidad, f"recinto {codigo}")
    return {
        "codigo_ign": codigo,
        "codigo_ine": codigo[-5:] if tipo == MUNICIPIO else None,
        "nombre": unidad.findtext(".//gn:text", namespaces=NS),
        "tipo_recinto": tipo,
        "n_poligonos": n_poligonos,
        "superficie_km2": round(superficie, 3),
    }


def leer_recintos(ruta_zip=RUTA_ZIP):
    """Lee todos los recintos municipales del GML del IGN (sin cargarlo entero en memoria)."""
    filas, raiz = [], None
    with zipfile.ZipFile(ruta_zip) as z, z.open(ARCHIVO_MUNICIPIOS) as gml:
        for evento, elemento in ET.iterparse(gml, events=("start", "end")):
            if raiz is None:
                raiz = elemento                   # wfs:FeatureCollection
            if evento == "end" and elemento.tag == ETIQUETA_UNIDAD:
                filas.append(describir_unidad(elemento))
                raiz.clear()                      # libera lo ya procesado
    return pd.DataFrame(filas).sort_values("codigo_ign").reset_index(drop=True)


# ---------------- Comprobaciones ----------------

def comprobar_lista_maestra(recintos, ruta=RUTA_MUNICIPIOS):
    """Avisa si algún municipio de la lista maestra no tiene recinto (o al revés)."""
    if not ruta.exists():
        print(f"Aviso: no existe {ruta}; no se comprueba la lista maestra")
        return
    maestra = set(pd.read_csv(ruta, dtype={"codigo_ine": str})["codigo_ine"].str.zfill(5))
    con_recinto = set(recintos["codigo_ine"].dropna())
    print(f"Municipios de la lista maestra con superficie: {len(maestra & con_recinto)} de {len(maestra)}")
    if maestra - con_recinto:
        print(f"Aviso: sin recinto en el IGN: {sorted(maestra - con_recinto)[:10]}")
    if con_recinto - maestra:
        print(f"Aviso: recintos del IGN que no están en la lista maestra: {sorted(con_recinto - maestra)[:10]}")


def comparar_con_wikidata(recintos, ruta=RUTA_WIKIDATA):
    """Compara la superficie calculada con la de Wikidata (solo informa)."""
    if not ruta.exists():
        return
    wikidata = pd.read_csv(ruta, dtype={"codigo_ine": str}, encoding="utf-8-sig")
    wikidata["codigo_ine"] = wikidata["codigo_ine"].str.zfill(5)
    municipios = recintos[recintos["codigo_ine"].notna()]   # los condominios no tienen INE
    cruce = municipios.merge(wikidata[["codigo_ine", "superficie_km2"]], on="codigo_ine",
                           suffixes=("", "_wikidata")).query("superficie_km2_wikidata > 0")
    diferencia = (cruce["superficie_km2"] / cruce["superficie_km2_wikidata"] - 1) * 100
    grandes = cruce[diferencia.abs() > DIFERENCIA_AVISO_PCT]
    print(f"Comparación con Wikidata ({len(cruce)} municipios): diferencia mediana "
          f"{diferencia.abs().median():.2f} %; {len(grandes)} con más del {DIFERENCIA_AVISO_PCT} %")


def main():
    if not RUTA_ZIP.exists():
        print(f"ERROR: falta {RUTA_ZIP}. Recupéralo con: git restore --source=c276ce6 data/raw")
        return 1
    print(f"Leyendo {ARCHIVO_MUNICIPIOS} de {RUTA_ZIP} (tarda un poco) ...")
    recintos = leer_recintos()
    print(recintos["tipo_recinto"].value_counts().to_string())
    comprobar_lista_maestra(recintos)
    comparar_con_wikidata(recintos)
    RUTA_SALIDA.parent.mkdir(parents=True, exist_ok=True)
    recintos.to_csv(RUTA_SALIDA, index=False, encoding="utf-8-sig")
    print(f"{len(recintos)} recintos ({recintos['superficie_km2'].sum():,.0f} km² en total) -> {RUTA_SALIDA}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
