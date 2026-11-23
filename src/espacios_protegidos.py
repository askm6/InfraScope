"""Espacios protegidos de la Red Natura 2000 cerca de cada municipio.

Fuentes (se descargan a data/raw/medioambiente/ si no están):
  - MITECO, capa oficial de la Red Natura 2000 (actualización de diciembre de 2025) en GML
    INSPIRE: código, nombre, figura de protección (ZEPA / LIC / ZEC) y polígonos de todos
    los espacios de España.
  - Natural Earth, tierra emergida a escala 1:10 millones (dominio público): sirve para
    calcular qué parte de cada espacio es mar, porque la capa del MITECO no lo indica.

Para cada municipio de data/processed/municipios.csv se mide la distancia desde su centro
(latitud/longitud) hasta el borde de cada espacio a menos de 25 km (0 = el centro está
dentro del espacio). Se mide en coordenadas UTM: huso 28 en Canarias y huso 30 en el resto.

Salidas en data/processed/:
  - espacios_protegidos_limpio.csv: una fila por municipio y espacio cercano.
  - espacios_protegidos_municipios.csv: indicadores por municipio.

Uso: python src/espacios_protegidos.py   (o python run_pipeline.py --solo espacios_protegidos)
     Para forzar una descarga nueva, borra los archivos de data/raw/medioambiente/.
"""
import json
import time
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from matplotlib.path import Path as Trazado
from PIL import Image, ImageDraw
from scipy.spatial import cKDTree

# ---------------- Configuración ----------------
CARPETA_RAW = Path("data/raw/medioambiente")
URL_NATURA = ("https://www.miteco.gob.es/content/dam/miteco/es/biodiversidad/servicios/"
              "banco-datos-naturaleza/3-rn2000/PS.Natura2000_2025_gml.zip")
RUTA_NATURA = CARPETA_RAW / "miteco_rednatura2000_2025_gml.zip"
URL_TIERRA = ("https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/"
              "geojson/ne_10m_land.geojson")
RUTA_TIERRA = CARPETA_RAW / "naturalearth_10m_tierra.geojson"
RUTA_MUNICIPIOS = Path("data/processed/municipios.csv")  # codigo_ine, municipio, latitud, longitud
CABECERA_HTTP = {"User-Agent": "Proyecto3-datos/1.0 (proyecto academico)"}

RUTA_SALIDA_ESPACIOS = Path("data/processed/espacios_protegidos_limpio.csv")
RUTA_SALIDA_MUNICIPIOS = Path("data/processed/espacios_protegidos_municipios.csv")

RADIO_MAX_KM = 25                 # solo se guardan los espacios a menos de esta distancia
RADIOS_KM = [5, 10, 25]
DISTANCIA_SEGURA_KM = 10          # a partir de aquí se considera que no condiciona el CPD
MARINO_MIN_PCT = 50               # espacio "marino" si más de la mitad de su superficie es mar
PASO_BORDE_M = 20                 # el borde se muestrea cada 20 m (error máximo de 10 m)
PROVINCIAS_CANARIAS = {"35", "38"}

# Tipos de espacio de la Red Natura 2000 (los mismos códigos que usa el MITECO)
TIPOS = {
    "A": "ZEPA (Directiva Aves)",
    "B": "LIC/ZEC (Directiva Hábitats)",
    "C": "ZEPA y LIC/ZEC",
}
# Si no se puede calcular el % marino, se deduce por el código (ESZZ = espacios marinos)
# o por el nombre
PALABRAS_MARINO = r"marin|submarin|corredor migratorio|sebadal|fondos marinos|bahía de"

# Zona (longitud y latitud mínimas y máximas) del mapa de tierra para cada huso. Todo lo
# que quede fuera se considera mar
RESOLUCION_TIERRA = 0.002         # grados por píxel (unos 200 m)
VENTANAS_TIERRA = {28: (-18.5, 27.4, -13.0, 29.6), 30: (-10.0, 34.8, 5.0, 44.2)}


# ---------------- Coordenadas UTM (ETRS89) ----------------
# Fórmulas de Krüger para la proyección transversa de Mercator (elipsoide GRS80). Sirven
# para pasar de latitud/longitud a metros y al revés sin instalar librerías de SIG.
_F = 1 / 298.257222101
_N = _F / (2 - _F)
_E = np.sqrt(_F * (2 - _F))
_A = 6378137.0 / (1 + _N) * (1 + _N ** 2 / 4 + _N ** 4 / 64)
_K0, _FALSO_ESTE = 0.9996, 500000.0
_ALFA = [_N / 2 - 2 / 3 * _N ** 2 + 5 / 16 * _N ** 3, 13 / 48 * _N ** 2 - 3 / 5 * _N ** 3,
         61 / 240 * _N ** 3]
_BETA = [_N / 2 - 2 / 3 * _N ** 2 + 37 / 96 * _N ** 3, 1 / 48 * _N ** 2 + 1 / 15 * _N ** 3,
         17 / 480 * _N ** 3]
_DELTA = [2 * _N - 2 / 3 * _N ** 2 - 2 * _N ** 3, 7 / 3 * _N ** 2 - 8 / 5 * _N ** 3,
          56 / 15 * _N ** 3]


def meridiano_central(huso):
    return -183 + 6 * huso


def a_utm(lat, lon, huso):
    """Latitud/longitud (grados) -> (x, y) en metros en el huso UTM indicado."""
    phi = np.radians(lat)
    lam = np.radians(np.asarray(lon) - meridiano_central(huso))
    t = np.sinh(np.arctanh(np.sin(phi)) - _E * np.arctanh(_E * np.sin(phi)))
    xi, eta = np.arctan2(t, np.cos(lam)), np.arctanh(np.sin(lam) / np.sqrt(1 + t ** 2))
    x, y = eta.copy(), xi.copy()
    for j, a in enumerate(_ALFA, 1):
        x += a * np.cos(2 * j * xi) * np.sinh(2 * j * eta)
        y += a * np.sin(2 * j * xi) * np.cosh(2 * j * eta)
    return _FALSO_ESTE + _K0 * _A * x, _K0 * _A * y


def de_utm(x, y, huso):
    """(x, y) en metros en el huso UTM indicado -> latitud/longitud (grados)."""
    xi, eta = np.asarray(y) / (_K0 * _A), (np.asarray(x) - _FALSO_ESTE) / (_K0 * _A)
    xi2, eta2 = xi.copy(), eta.copy()
    for j, b in enumerate(_BETA, 1):
        xi2 -= b * np.sin(2 * j * xi) * np.cosh(2 * j * eta)
        eta2 -= b * np.cos(2 * j * xi) * np.sinh(2 * j * eta)
    chi = np.arcsin(np.sin(xi2) / np.cosh(eta2))
    phi = chi.copy()
    for j, d in enumerate(_DELTA, 1):
        phi += d * np.sin(2 * j * chi)
    lam = np.arctan2(np.sinh(eta2), np.cos(xi2))
    return np.degrees(phi), np.degrees(lam) + meridiano_central(huso)


def huso_municipio(codigo_ine):
    return 28 if str(codigo_ine)[:2] in PROVINCIAS_CANARIAS else 30


# ---------------- Descarga ----------------
def descargar(url, ruta, reintentos=8, forzar=False):
    """Descarga `url` a `ruta` si no existe (o siempre, con forzar=True; el archivo viejo
    solo se sustituye cuando el nuevo está completo). El servidor del MITECO corta a veces
    la conexión a mitad de descarga: se continúa desde donde se quedó (cabecera Range)."""
    if ruta.exists() and not forzar:
        return
    ruta.parent.mkdir(parents=True, exist_ok=True)
    parcial = ruta.with_name(ruta.name + ".parcial")
    print(f"Descargando {url} ...", flush=True)
    for intento in range(1, reintentos + 1):
        ya = parcial.stat().st_size if parcial.exists() else 0
        cabecera = {**CABECERA_HTTP, **({"Range": f"bytes={ya}-"} if ya else {})}
        try:
            with requests.get(url, headers=cabecera, stream=True, timeout=120) as r:
                if r.status_code == 416:           # ya estaba completo
                    break
                r.raise_for_status()
                if ya and r.status_code != 206:    # el servidor no admite Range: se empieza de 0
                    ya = 0
                total = ya + int(r.headers.get("Content-Length", 0))
                with open(parcial, "ab" if ya else "wb") as f:
                    for trozo in r.iter_content(1 << 20):
                        f.write(trozo)
            if parcial.stat().st_size >= total:
                break
        except requests.RequestException as e:
            print(f"  intento {intento}: {type(e).__name__}, se reintenta", flush=True)
        time.sleep(2)
    else:
        raise RuntimeError(f"No se ha podido descargar {url}")
    parcial.replace(ruta)


# ---------------- Lectura de la capa del MITECO ----------------
def tipo_espacio(designaciones):
    """ZEPA = A, LIC/ZEC = B, ambas = C. El GML del MITECO escribe a veces
    'SpecialProtecionArea' (sin la t), por eso se busca 'protec'."""
    texto = " ".join(designaciones).lower()
    zepa = "specialprotec" in texto
    lic = "communityimportance" in texto or "areaofconservation" in texto
    return "C" if zepa and lic else "A" if zepa else "B" if lic else None


def leer_espacios(ruta_zip):
    """Lee los GML (península + Canarias) y devuelve una lista de espacios con sus anillos
    (exteriores y huecos) en metros UTM, en el huso 28 (Canarias) o 30 (el resto)."""
    gml = "{http://www.opengis.net/gml/3.2}"
    href = "{http://www.w3.org/1999/xlink}href"
    espacios = []
    with zipfile.ZipFile(ruta_zip) as z:
        for nombre in sorted(n for n in z.namelist() if n.lower().endswith(".gml")):
            with z.open(nombre) as f:
                for _, el in ET.iterparse(f, events=("end",)):
                    if not el.tag.endswith("}ProtectedSite"):
                        continue
                    codigo = el.find(".//{*}localId")
                    nombre_esp = el.find(".//{*}SpellingOfName/{*}text")
                    designaciones = [d.get(href, "") for d in el.iter() if d.tag.endswith("}designation")]
                    # El GML usa EPSG:3040 (UTM huso 28) para todo, con el norte primero
                    anillos = []
                    for clase in ("exterior", "interior"):
                        for anillo in el.iter(gml + clase):
                            for pos in anillo.iter(gml + "posList"):
                                c = np.array(pos.text.split(), dtype=float).reshape(-1, 2)[:, ::-1]
                                anillos.append((clase == "exterior", c))
                    el.clear()
                    if codigo is None or not anillos:
                        continue
                    espacios.append({
                        "sitecode": codigo.text.strip(),
                        "sitename": nombre_esp.text.strip() if nombre_esp is not None else "",
                        "sitetype": tipo_espacio(designaciones),
                        "anillos": anillos,
                    })
    # Cada espacio se pasa a su huso: la península en huso 28 deforma mucho las distancias
    for esp in espacios:
        latlon = [de_utm(c[:, 0], c[:, 1], 28) for _, c in esp["anillos"]]
        esp["huso"] = 28 if np.concatenate([la for la, _ in latlon]).mean() < 31 else 30
        esp["anillos"] = [(ext, np.column_stack(a_utm(la, lo, esp["huso"])))
                          for (ext, _), (la, lo) in zip(esp["anillos"], latlon)]
        esp["area_ha"] = area_ha(esp["anillos"])
    print(f"Capa Red Natura 2000: {len(espacios)} espacios "
          f"({sum(e['huso'] == 28 for e in espacios)} en Canarias)")
    return espacios


def area_ha(anillos):
    """Superficie (fórmula del área de Gauss): exteriores menos huecos."""
    total = 0.0
    for exterior, c in anillos:
        a = 0.5 * abs(np.dot(c[:-1, 0], c[1:, 1]) - np.dot(c[1:, 0], c[:-1, 1]))
        total += a if exterior else -a
    return total / 1e4


def rasterizar(anillos, x0, y1, paso, ancho, alto):
    """Pinta los anillos (exteriores a 1, huecos a 0) en una imagen de ancho x alto
    píxeles cuya esquina superior izquierda es (x0, y1). Devuelve una matriz booleana."""
    img = Image.new("1", (ancho, alto), 0)
    dibujo = ImageDraw.Draw(img)
    for exterior, c in sorted(anillos, key=lambda a: not a[0]):    # primero los exteriores
        px = np.column_stack([(c[:, 0] - x0) / paso, (y1 - c[:, 1]) / paso])
        dibujo.polygon([tuple(p) for p in px], fill=1 if exterior else 0)
    return np.array(img, dtype=bool)


def mapas_tierra(ruta_geojson):
    """Un mapa de píxeles tierra/mar (en grados) por huso, a partir de Natural Earth."""
    with open(ruta_geojson, encoding="utf-8") as f:
        tierra = json.load(f)
    poligonos = []
    for feature in tierra["features"]:
        g = feature["geometry"]
        poligonos += g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
    mapas = {}
    for huso, (lon0, lat0, lon1, lat1) in VENTANAS_TIERRA.items():
        anillos = []
        for poligono in poligonos:
            for k, anillo in enumerate(poligono):
                c = np.asarray(anillo)
                if (c[:, 0].max() >= lon0 and c[:, 0].min() <= lon1
                        and c[:, 1].max() >= lat0 and c[:, 1].min() <= lat1):
                    anillos.append((k == 0, c))
        ancho = int((lon1 - lon0) / RESOLUCION_TIERRA)
        alto = int((lat1 - lat0) / RESOLUCION_TIERRA)
        mapas[huso] = rasterizar(anillos, lon0, lat1, RESOLUCION_TIERRA, ancho, alto)
    return mapas


def porcentaje_marino(esp, mapas):
    """% de la superficie del espacio que cae en el mar: se pinta el espacio en una
    cuadrícula de hasta 200 x 200 celdas y se mira cuántas caen en tierra."""
    todos = np.vstack([c for _, c in esp["anillos"]])
    (xmin, ymin), (xmax, ymax) = todos.min(0), todos.max(0)
    paso = max(25.0, max(xmax - xmin, ymax - ymin) / 200)
    dentro = rasterizar(esp["anillos"], xmin, ymax, paso,
                        int((xmax - xmin) / paso) + 1, int((ymax - ymin) / paso) + 1)
    fila, col = np.nonzero(dentro)
    if len(fila) == 0:                        # espacio más pequeño que una celda
        return np.nan
    lat, lon = de_utm(xmin + (col + 0.5) * paso, ymax - (fila + 0.5) * paso, esp["huso"])
    lon0, lat0, lon1, lat1 = VENTANAS_TIERRA[esp["huso"]]
    mapa = mapas[esp["huso"]]
    i = ((lat1 - lat) / RESOLUCION_TIERRA).astype(int)
    j = ((lon - lon0) / RESOLUCION_TIERRA).astype(int)
    en_mapa = (i >= 0) & (i < mapa.shape[0]) & (j >= 0) & (j < mapa.shape[1])
    en_tierra = np.zeros(len(i), dtype=bool)
    en_tierra[en_mapa] = mapa[i[en_mapa], j[en_mapa]]
    return round(100 * (1 - en_tierra.mean()))


# ---------------- Distancias a los municipios ----------------
def puntos_borde(anillos):
    """Puntos cada PASO_BORDE_M metros a lo largo de todos los bordes del espacio."""
    puntos = []
    for _, c in anillos:
        tramo = np.diff(c, axis=0)
        n = np.maximum(1, np.ceil(np.hypot(tramo[:, 0], tramo[:, 1]) / PASO_BORDE_M)).astype(int)
        idx = np.repeat(np.arange(len(tramo)), n)
        frac = (np.arange(n.sum()) - np.repeat(np.cumsum(n) - n, n)) / n[idx]
        puntos.append(c[idx] + tramo[idx] * frac[:, None])
    return np.vstack(puntos)


def distancias(espacios, muni):
    """Una fila por (municipio, espacio) a menos de RADIO_MAX_KM del centro del municipio."""
    con_coord = muni.dropna(subset=["latitud", "longitud"])
    codigos = con_coord["codigo_ine"].to_numpy()
    husos = con_coord["codigo_ine"].map(huso_municipio).to_numpy()
    x, y = np.empty(len(con_coord)), np.empty(len(con_coord))
    for huso in (28, 30):
        m = husos == huso
        x[m], y[m] = a_utm(con_coord["latitud"].to_numpy()[m], con_coord["longitud"].to_numpy()[m], huso)

    radio = RADIO_MAX_KM * 1000
    filas = []
    for esp in espacios:
        todos = np.vstack([c for _, c in esp["anillos"]])
        (xmin, ymin), (xmax, ymax) = todos.min(0), todos.max(0)
        cerca = np.flatnonzero((husos == esp["huso"]) & (x > xmin - radio) & (x < xmax + radio)
                               & (y > ymin - radio) & (y < ymax + radio))
        if len(cerca) == 0:
            continue
        pts = np.column_stack([x[cerca], y[cerca]])
        dist, _ = cKDTree(puntos_borde(esp["anillos"])).query(pts, distance_upper_bound=radio)
        # Centro dentro del espacio: un punto está dentro si lo está en un número impar
        # de anillos (así los huecos del polígono quedan fuera)
        dentro = np.zeros(len(cerca), dtype=bool)
        en_caja = (pts[:, 0] >= xmin) & (pts[:, 0] <= xmax) & (pts[:, 1] >= ymin) & (pts[:, 1] <= ymax)
        if en_caja.any():
            for _, c in esp["anillos"]:
                dentro[en_caja] ^= Trazado(c).contains_points(pts[en_caja])
        dist[dentro] = 0
        ok = np.isfinite(dist)
        filas += [(codigos[i], esp["sitecode"], esp["sitename"], esp["sitetype"],
                   round(esp["area_ha"]), esp["pct_area_marina"], round(d / 1000, 2))
                  for i, d in zip(cerca[ok], dist[ok])]
    return pd.DataFrame(filas, columns=["codigo_ine", "sitecode", "sitename", "sitetype",
                                        "area_ha", "pct_area_marina", "distancia_km"])


def cargar_datos(ruta_natura, ruta_tierra, ruta_municipios):
    """Espacios Red Natura 2000 a menos de 25 km de cada municipio, calculados a partir
    de los polígonos del MITECO."""
    inicio = time.time()
    espacios = leer_espacios(ruta_natura)
    mapas = mapas_tierra(ruta_tierra)
    for esp in espacios:
        esp["pct_area_marina"] = porcentaje_marino(esp, mapas)
    muni = pd.read_csv(ruta_municipios, dtype={"codigo_ine": str}, encoding="utf-8")
    muni["codigo_ine"] = muni["codigo_ine"].str.zfill(5)
    df = distancias(espacios, muni)
    print(f"Distancias calculadas: {len(df)} pares municipio-espacio "
          f"({time.time() - inicio:.0f} s)")
    return df


# ---------------- Limpieza e indicadores ----------------
def limpiar(df):
    """Quita filas inválidas y duplicados, clasifica el tipo de espacio y marca los marinos."""
    filas_inicio = len(df)
    df = df.dropna(subset=["codigo_ine", "sitecode", "distancia_km"]).copy()
    df["codigo_ine"] = df["codigo_ine"].str.strip().str.zfill(5)
    df["sitecode"] = df["sitecode"].str.strip().str.upper()
    df["sitename"] = df["sitename"].fillna("").str.strip()
    df["sitetype"] = df["sitetype"].str.strip().str.upper()

    # Códigos y valores válidos
    validos = df["sitecode"].str.match(r"^ES[0-9A-Z]{7}$") & df["sitetype"].isin(TIPOS)
    validos &= df["distancia_km"].between(0, RADIO_MAX_KM)
    if (~validos).any():
        print(f"Aviso: {(~validos).sum()} filas con código, tipo o distancia no válidos (se descartan)")
    df = df[validos]
    df.loc[df["area_ha"] <= 0, "area_ha"] = pd.NA

    # Un mismo espacio puede salir repetido para un municipio: nos quedamos con la menor distancia
    df = df.sort_values("distancia_km").drop_duplicates(subset=["codigo_ine", "sitecode"], keep="first")

    df["tipo"] = df["sitetype"].map(TIPOS)
    deducido = df["sitecode"].str.startswith("ESZZ") | df["sitename"].str.contains(
        PALABRAS_MARINO, case=False, regex=True)
    df["es_marino"] = (df["pct_area_marina"] >= MARINO_MIN_PCT).where(df["pct_area_marina"].notna(), deducido)
    df["dentro"] = df["distancia_km"] == 0

    print(f"Filas: {filas_inicio} calculadas -> {len(df)} limpias "
          f"({df['sitecode'].nunique()} espacios distintos, {df['es_marino'].sum()} filas marinas)")
    columnas = ["codigo_ine", "sitecode", "sitename", "sitetype", "tipo", "area_ha", "pct_area_marina",
                "es_marino", "distancia_km", "dentro"]
    return df.sort_values(["codigo_ine", "distancia_km"])[columnas].reset_index(drop=True)


def resumir_municipios(espacios, ruta_municipios):
    """Indicadores por municipio. Solo cuentan los espacios terrestres: los marinos no
    limitan dónde se puede construir, pero se cuentan aparte por si se quieren usar."""
    muni = pd.read_csv(ruta_municipios, dtype={"codigo_ine": str}, encoding="utf-8")
    muni["codigo_ine"] = muni["codigo_ine"].str.zfill(5)
    tierra = espacios[~espacios["es_marino"].astype(bool)]

    res = muni[["codigo_ine", "municipio"]].copy()
    cercano = tierra.groupby("codigo_ine").first()        # ya ordenado por distancia
    res = res.merge(cercano[["sitecode", "sitename", "tipo", "distancia_km"]].rename(columns={
        "sitecode": "espacio_mas_cercano_codigo", "sitename": "espacio_mas_cercano",
        "tipo": "espacio_mas_cercano_tipo", "distancia_km": "dist_min_km"}),
        left_on="codigo_ine", right_index=True, how="left")

    for r in RADIOS_KM:
        n = tierra[tierra["distancia_km"] <= r].groupby("codigo_ine")["sitecode"].nunique()
        res[f"n_espacios_{r}km"] = res["codigo_ine"].map(n).fillna(0).astype(int)
    area10 = tierra[tierra["distancia_km"] <= 10].groupby("codigo_ine")["area_ha"].sum()
    res["area_protegida_10km_ha"] = res["codigo_ine"].map(area10).fillna(0).round(0)
    marinos = espacios[espacios["es_marino"].astype(bool)].groupby("codigo_ine")["sitecode"].nunique()
    res["n_espacios_marinos_25km"] = res["codigo_ine"].map(marinos).fillna(0).astype(int)

    # Sin espacios terrestres en 25 km: la distancia real es "más de 25"
    res["sin_espacios_25km"] = res["dist_min_km"].isna()
    res["dist_min_km"] = res["dist_min_km"].fillna(RADIO_MAX_KM)
    res["centro_dentro_espacio"] = res["dist_min_km"] == 0

    # Riesgo ambiental/regulatorio: cuanto más cerca y más espacios, más trámites (evaluación
    # ambiental, posibles limitaciones de uso del suelo)
    res["riesgo_ambiental"] = pd.cut(res["dist_min_km"], bins=[-0.01, 2, 5, 1000],
                                     labels=["alto", "medio", "bajo"])
    # Puntuación 0-100 (100 = sin condicionantes): 70% distancia, 30% densidad de espacios a 10 km
    distancia = (res["dist_min_km"] / DISTANCIA_SEGURA_KM).clip(upper=1)
    densidad = 1 - (res["n_espacios_10km"] / 10).clip(upper=1)
    res["puntuacion_ambiental"] = (70 * distancia + 30 * densidad).round(1)

    # Municipios sin coordenadas: no se ha podido medir nada, se dejan vacíos (no son
    # "municipios sin espacios cerca")
    sin_coord = muni["latitud"].isna() | muni["longitud"].isna()
    if sin_coord.any():
        afectados = res["codigo_ine"].isin(muni.loc[sin_coord, "codigo_ine"])
        columnas_medidas = [c for c in res.columns if c not in ("codigo_ine", "municipio")]
        res[columnas_medidas] = res[columnas_medidas].astype(object)
        res.loc[afectados, columnas_medidas] = pd.NA
        print(f"Aviso: {afectados.sum()} municipios sin coordenadas: indicadores vacíos")

    n_sin = int(res["sin_espacios_25km"].eq(True).sum())
    print(f"Municipios: {len(res)} ({n_sin} sin ningún espacio terrestre a menos de {RADIO_MAX_KM} km)")
    return res.sort_values("puntuacion_ambiental", ascending=False).reset_index(drop=True)


if __name__ == "__main__":
    descargar(URL_NATURA, RUTA_NATURA)
    descargar(URL_TIERRA, RUTA_TIERRA)
    espacios = limpiar(cargar_datos(RUTA_NATURA, RUTA_TIERRA, RUTA_MUNICIPIOS))
    municipios = resumir_municipios(espacios, RUTA_MUNICIPIOS)

    espacios.to_csv(RUTA_SALIDA_ESPACIOS, index=False, encoding="utf-8-sig")
    municipios.to_csv(RUTA_SALIDA_MUNICIPIOS, index=False, encoding="utf-8-sig")

    columnas = ["municipio", "dist_min_km", "espacio_mas_cercano", "n_espacios_10km",
                "riesgo_ambiental", "puntuacion_ambiental"]
    print("\nMuestra de municipios (100 = sin condicionantes ambientales):")
    print(municipios[columnas].sample(10, random_state=1).to_string(index=False))
    print(f"\nGuardado: {RUTA_SALIDA_ESPACIOS}, {RUTA_SALIDA_MUNICIPIOS}")
