import numpy as np
import pandas as pd

# ---------------- Configuración ----------------
RUTA_ENTRADA = "data/raw/transporte/aeropuertos.csv"         # formato OurAirports
RUTA_MUNICIPIOS = "data/processed/municipios.csv"            # codigo_ine, municipio, latitud, longitud
RUTA_SALIDA_AEROPUERTOS = "data/processed/aeropuertos.csv"
RUTA_SALIDA_MUNICIPIOS = "data/processed/aeropuertos_municipios.csv"

NUM_MUNICIPIOS = 29
RADIO_KM = 100                      # se cuentan los aeropuertos a menos de esta distancia
DISTANCIA_MAXIMA_KM = 150           # a esta distancia (o más) del aeropuerto grande -> índice 0

# Rango aproximado de España (península, Baleares, Canarias, Ceuta y Melilla)
LATITUD_MIN, LATITUD_MAX = 27.0, 44.5
LONGITUD_MIN, LONGITUD_MAX = -18.5, 4.5

TIPOS = {"large_airport": "grande", "medium_airport": "mediano", "small_airport": "pequeño"}

# Código ISO de la región -> nombre de la comunidad como en el INE (igual que en energia.py)
CCAA_ISO = {
    "ES-AN": "Andalucía", "ES-AR": "Aragón", "ES-AS": "Asturias, Principado de",
    "ES-IB": "Balears, Illes", "ES-CN": "Canarias", "ES-CB": "Cantabria",
    "ES-CL": "Castilla y León", "ES-CM": "Castilla - La Mancha", "ES-CT": "Cataluña",
    "ES-VC": "Comunitat Valenciana", "ES-EX": "Extremadura", "ES-GA": "Galicia",
    "ES-MD": "Madrid, Comunidad de", "ES-MC": "Murcia, Región de",
    "ES-NC": "Navarra, Comunidad Foral de", "ES-PV": "País Vasco", "ES-RI": "Rioja, La",
    "ES-CE": "Ceuta", "ES-ML": "Melilla",
}


def cargar_datos():
    """Lee los aeropuertos y la lista de municipios (código INE como texto de 5 dígitos)."""
    aeropuertos = pd.read_csv(RUTA_ENTRADA, encoding="utf-8")
    municipios = pd.read_csv(RUTA_MUNICIPIOS, dtype={"codigo_ine": str}, encoding="utf-8")
    municipios["codigo_ine"] = municipios["codigo_ine"].astype(str).str.strip().str.zfill(5)
    return aeropuertos, municipios


def limpiar_aeropuertos(df):
    """Renombra columnas, traduce tipo y comunidad y descarta filas sin coordenadas válidas."""
    df = df.rename(columns={
        "ident": "codigo_icao", "iata_code": "codigo_iata", "name": "nombre",
        "type": "tipo", "latitude_deg": "latitud", "longitude_deg": "longitud",
        "iso_region": "region_iso", "municipality": "localidad",
    })
    for col in ["codigo_icao", "codigo_iata", "nombre", "tipo", "region_iso", "localidad"]:
        df[col] = df[col].astype("string").str.strip()
    for col in ["latitud", "longitud"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    nulos = df[["codigo_icao", "nombre", "latitud", "longitud"]].isna().sum()
    if nulos.any():
        print(f"Aviso: valores nulos (se quitan esas filas) -> {nulos[nulos > 0].to_dict()}")
    df = df.dropna(subset=["codigo_icao", "nombre", "latitud", "longitud"])

    duplicados = df.duplicated(subset=["codigo_icao"]).sum()
    if duplicados:
        print(f"Aviso: {duplicados} aeropuertos repetidos (se quita la repetición)")
        df = df.drop_duplicates(subset=["codigo_icao"])

    fuera = ~(df["latitud"].between(LATITUD_MIN, LATITUD_MAX)
              & df["longitud"].between(LONGITUD_MIN, LONGITUD_MAX))
    if fuera.any():
        print(f"Aviso: coordenadas fuera de España (se quitan): "
              f"{df.loc[fuera, 'codigo_icao'].tolist()}")
        df = df[~fuera]

    df["tipo"] = df["tipo"].map(TIPOS).fillna(df["tipo"])
    df["ccaa"] = df["region_iso"].map(CCAA_ISO)
    if df["ccaa"].isna().any():
        print(f"Aviso: regiones sin traducir: {sorted(df.loc[df['ccaa'].isna(), 'region_iso'].unique())}")

    columnas = ["codigo_icao", "codigo_iata", "nombre", "tipo", "ccaa", "localidad",
                "latitud", "longitud"]
    return df[columnas].sort_values(["ccaa", "nombre"]).reset_index(drop=True)


def limpiar_municipios(df):
    """Comprueba que están los 29 municipios con coordenadas."""
    df = df.drop_duplicates(subset=["codigo_ine"]).copy()
    for col in ["latitud", "longitud"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    sin_coordenadas = df[df[["latitud", "longitud"]].isna().any(axis=1)]
    if len(sin_coordenadas):
        print(f"Aviso: municipios sin coordenadas (se quitan): {sin_coordenadas['municipio'].tolist()}")
        df = df.dropna(subset=["latitud", "longitud"])
    if len(df) != NUM_MUNICIPIOS:
        print(f"Aviso: hay {len(df)} municipios en vez de {NUM_MUNICIPIOS}")
    return df[["codigo_ine", "municipio", "provincia", "latitud", "longitud"]]


def distancias_km(municipios, aeropuertos):
    """Matriz de distancias en línea recta (fórmula del haversine): municipios x aeropuertos."""
    radio_tierra = 6371.0
    lat1 = np.radians(municipios["latitud"].to_numpy())[:, None]
    lon1 = np.radians(municipios["longitud"].to_numpy())[:, None]
    lat2 = np.radians(aeropuertos["latitud"].to_numpy())[None, :]
    lon2 = np.radians(aeropuertos["longitud"].to_numpy())[None, :]
    a = (np.sin((lat2 - lat1) / 2) ** 2
         + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2)
    return 2 * radio_tierra * np.arcsin(np.sqrt(a))


def mas_cercano(municipios, aeropuertos, distancias, prefijo):
    """Para cada municipio, el aeropuerto más cercano (nombre, IATA y distancia)."""
    posicion = distancias.argmin(axis=1)
    elegido = aeropuertos.iloc[posicion].reset_index(drop=True)
    return pd.DataFrame({
        "codigo_ine": municipios["codigo_ine"].to_numpy(),
        f"{prefijo}_nombre": elegido["nombre"].to_numpy(),
        f"{prefijo}_iata": elegido["codigo_iata"].to_numpy(),
        f"{prefijo}_km": distancias.min(axis=1).round(1),
    })


def calcular(municipios, aeropuertos):
    """Una fila por municipio: aeropuerto más cercano, el grande más cercano y nº en el radio."""
    todas = distancias_km(municipios, aeropuertos)
    grandes = aeropuertos[aeropuertos["tipo"] == "grande"].reset_index(drop=True)
    dist_grandes = distancias_km(municipios, grandes)

    df = (municipios.merge(mas_cercano(municipios, aeropuertos, todas, "aeropuerto"),
                           on="codigo_ine")
                    .merge(mas_cercano(municipios, grandes, dist_grandes, "aeropuerto_grande"),
                           on="codigo_ine"))
    df[f"aeropuertos_{RADIO_KM}km"] = (todas <= RADIO_KM).sum(axis=1)

    # 1 = aeropuerto grande en el propio municipio, 0 = a DISTANCIA_MAXIMA_KM o más
    df["indice_accesibilidad_aerea"] = (
        1 - (df["aeropuerto_grande_km"] / DISTANCIA_MAXIMA_KM).clip(upper=1)).round(3)

    df = df.drop(columns=["latitud", "longitud"])
    return df.sort_values("indice_accesibilidad_aerea", ascending=False).reset_index(drop=True)


if __name__ == "__main__":
    aeropuertos_brutos, municipios_brutos = cargar_datos()
    aeropuertos = limpiar_aeropuertos(aeropuertos_brutos)
    municipios = limpiar_municipios(municipios_brutos)
    resultado = calcular(municipios, aeropuertos)

    aeropuertos.to_csv(RUTA_SALIDA_AEROPUERTOS, index=False, encoding="utf-8-sig")
    resultado.to_csv(RUTA_SALIDA_MUNICIPIOS, index=False, encoding="utf-8-sig")

    print(f"Aeropuertos: {len(aeropuertos)} "
          f"({aeropuertos['tipo'].value_counts().to_dict()}) | municipios: {len(resultado)}")
    columnas = ["municipio", "aeropuerto_iata", "aeropuerto_km", "aeropuerto_grande_iata",
                "aeropuerto_grande_km", f"aeropuertos_{RADIO_KM}km", "indice_accesibilidad_aerea"]
    print("\n5 municipios con MEJOR acceso a un aeropuerto grande:")
    print(resultado.head(5)[columnas].to_string(index=False))
    print("\n5 municipios con PEOR acceso a un aeropuerto grande:")
    print(resultado.tail(5)[columnas].to_string(index=False))
    print(f"\nResultado guardado en {RUTA_SALIDA_AEROPUERTOS} y {RUTA_SALIDA_MUNICIPIOS}")
