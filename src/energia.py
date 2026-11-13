import pandas as pd

# ---------------- Configuración ----------------
CARPETA_ENTRADA = "data/raw/energia/"
RUTA_DEMANDA_CCAA = CARPETA_ENTRADA + "ree_demanda_ccaa_anual.csv"
RUTA_RENOVABLES_CCAA = CARPETA_ENTRADA + "ree_generacion_renovable_ccaa_anual.csv"
RUTA_PRECIOS = CARPETA_ENTRADA + "ree_precios_horarios.csv"   # de src/ree_precios_descarga.py

RUTA_SALIDA_CCAA = "data/processed/energia_ccaa_anual.csv"
RUTA_SALIDA_PICOS_PRECIO = "data/processed/energia_picos_precio.csv"

# Datos por comunidad: solo el último año de los datos
SERIE_PRECIO = "Precio mercado spot"   # la única serie de REE con todos los años (PVPC: desde 2021)
                                       # los picos de precio usan TODOS los años disponibles

# REE escribe las comunidades sin tildes; las pasamos a los nombres del INE
# (los mismos que usa poblacion_provincias.csv) para poder cruzar los datos.
NOMBRES_CCAA = {
    "Andalucia": "Andalucía",
    "Aragon": "Aragón",
    "Asturias": "Asturias, Principado de",
    "Illes Balears": "Balears, Illes",
    "Canarias": "Canarias",
    "Cantabria": "Cantabria",
    "Castilla-La Mancha": "Castilla - La Mancha",
    "Castilla y Leon": "Castilla y León",
    "Cataluna": "Cataluña",
    "Comunitat Valenciana": "Comunitat Valenciana",
    "Extremadura": "Extremadura",
    "Galicia": "Galicia",
    "Madrid": "Madrid, Comunidad de",
    "Murcia": "Murcia, Región de",
    "Navarra": "Navarra, Comunidad Foral de",
    "Pais Vasco": "País Vasco",
    "La Rioja": "Rioja, La",
}


def normalizar_ccaa(df):
    """Quita espacios y traduce el nombre de la comunidad al formato del INE."""
    df["ccaa"] = df["ccaa"].str.strip()
    desconocidas = set(df["ccaa"]) - set(NOMBRES_CCAA)
    if desconocidas:
        print(f"Aviso: comunidades sin traducir: {sorted(desconocidas)}")
    df["ccaa"] = df["ccaa"].map(NOMBRES_CCAA).fillna(df["ccaa"])
    return df


def limpiar_demanda_ccaa(ruta):
    """Demanda eléctrica anual por comunidad. Solo años completos (12 meses)."""
    df = pd.read_csv(ruta, encoding="utf-8")
    df["anio"] = pd.to_numeric(df["anio"], errors="coerce")
    df["demanda_mwh"] = pd.to_numeric(df["demanda_mwh"], errors="coerce")
    df = df.dropna(subset=["ccaa", "anio", "demanda_mwh"])
    df = df[(df["meses"] == 12) & (df["demanda_mwh"] > 0)]
    df = normalizar_ccaa(df)
    df["anio"] = df["anio"].astype(int)
    return df.drop_duplicates(subset=["ccaa", "anio"])[["ccaa", "anio", "demanda_mwh"]]


def limpiar_renovables_ccaa(ruta):
    """Generación anual por comunidad, separada en renovable y no renovable."""
    df = pd.read_csv(ruta, encoding="utf-8")
    df["anio"] = pd.to_numeric(df["anio"], errors="coerce")
    df["generacion_mwh"] = pd.to_numeric(df["generacion_mwh"], errors="coerce")
    df["tipo"] = df["tipo"].str.strip().str.lower()
    df = df.dropna(subset=["ccaa", "anio", "tipo", "generacion_mwh"])
    df = df[df["generacion_mwh"] >= 0]
    df = normalizar_ccaa(df)
    df["anio"] = df["anio"].astype(int)
    df = df.drop_duplicates(subset=["ccaa", "anio", "tipo"])

    # Una fila por comunidad y año, con una columna por tipo
    tabla = (df.pivot(index=["ccaa", "anio"], columns="tipo", values="generacion_mwh")
               .rename(columns={"renovable": "generacion_renovable_mwh",
                                "no renovable": "generacion_no_renovable_mwh"})
               .reset_index())
    tabla.columns.name = None
    tabla["generacion_total_mwh"] = (tabla["generacion_renovable_mwh"]
                                     + tabla["generacion_no_renovable_mwh"])
    tabla["renovable_pct"] = (tabla["generacion_renovable_mwh"]
                              / tabla["generacion_total_mwh"] * 100).round(1)
    return tabla


def unir_ccaa(demanda, renovables):
    """Junta demanda y generación y calcula cuánto cubre la comunidad con lo que produce."""
    df = demanda.merge(renovables, on=["ccaa", "anio"], how="outer")
    # > 100 %: la comunidad genera más de lo que consume (exporta electricidad)
    df["autoabastecimiento_pct"] = (df["generacion_total_mwh"] / df["demanda_mwh"] * 100).round(1)
    columnas = ["ccaa", "anio", "demanda_mwh", "generacion_renovable_mwh",
                "generacion_no_renovable_mwh", "generacion_total_mwh",
                "renovable_pct", "autoabastecimiento_pct"]
    return df[columnas].sort_values(["ccaa", "anio"]).reset_index(drop=True)


def picos_precio(ruta):
    """Por año, el día con el precio medio más alto y el más bajo del mercado eléctrico."""
    df = pd.read_csv(ruta, encoding="utf-8")
    df = df[df["serie"] == SERIE_PRECIO].copy()
    df["precio_eur_mwh"] = pd.to_numeric(df["precio_eur_mwh"], errors="coerce")
    # Hora local española; hasta 2024 hay un dato por hora y desde 2025 uno cada 15 min
    df["momento"] = pd.to_datetime(df["datetime"], utc=True, errors="coerce").dt.tz_convert("Europe/Madrid")
    df = df.dropna(subset=["momento", "precio_eur_mwh"])
    df = df.drop_duplicates(subset=["momento"])
    df["fecha"] = df["momento"].dt.date

    diario = df.groupby("fecha", as_index=False).agg(precio_eur_mwh=("precio_eur_mwh", "mean"))
    diario["fecha"] = pd.to_datetime(diario["fecha"])
    diario["anio"] = diario["fecha"].dt.year
    resumen = diario.groupby("anio").agg(media_anual_eur_mwh=("precio_eur_mwh", "mean"),
                                         dias_con_dato=("fecha", "nunique"))

    filas = []
    for tipo, indices in [("alto", diario.groupby("anio")["precio_eur_mwh"].idxmax()),
                          ("bajo", diario.groupby("anio")["precio_eur_mwh"].idxmin())]:
        picos = diario.loc[indices].assign(tipo=tipo)
        filas.append(picos)
    picos = pd.concat(filas).merge(resumen, on="anio", how="left")
    picos["diferencia_vs_media"] = picos["precio_eur_mwh"] - picos["media_anual_eur_mwh"]
    for col in ["precio_eur_mwh", "media_anual_eur_mwh", "diferencia_vs_media"]:
        picos[col] = picos[col].round(2)
    picos["fecha"] = picos["fecha"].dt.strftime("%Y-%m-%d")
    picos["serie"] = SERIE_PRECIO
    columnas = ["anio", "tipo", "fecha", "precio_eur_mwh", "media_anual_eur_mwh",
                "diferencia_vs_media", "dias_con_dato", "serie"]
    return picos[columnas].sort_values(["anio", "tipo"]).reset_index(drop=True)


if __name__ == "__main__":
    ccaa = unir_ccaa(limpiar_demanda_ccaa(RUTA_DEMANDA_CCAA),
                     limpiar_renovables_ccaa(RUTA_RENOVABLES_CCAA))

    # Solo datos recientes: último año por comunidad
    ccaa = ccaa[ccaa["anio"] == ccaa["anio"].max()].reset_index(drop=True)

    ccaa.to_csv(RUTA_SALIDA_CCAA, index=False, encoding="utf-8-sig")

    picos = picos_precio(RUTA_PRECIOS)
    picos.to_csv(RUTA_SALIDA_PICOS_PRECIO, index=False, encoding="utf-8-sig")

    ultimo = ccaa["anio"].max()
    print(f"Comunidades: {ccaa['ccaa'].nunique()} | años {ccaa['anio'].min()}-{ultimo} "
          f"| filas: {len(ccaa)}")
    huecos = ccaa.isna().sum().sum()
    if huecos:
        print(f"Aviso: {huecos} valores vacíos tras unir las tablas")

    print(f"\n% renovable y autoabastecimiento por comunidad en {ultimo}:")
    print(ccaa[ccaa["anio"] == ultimo]
          .sort_values("renovable_pct", ascending=False)
          [["ccaa", "demanda_mwh", "generacion_total_mwh", "renovable_pct",
            "autoabastecimiento_pct"]]
          .to_string(index=False))

    print(f"\nPicos de precio diario ({SERIE_PRECIO}, €/MWh) por año:")
    print(picos.pivot(index="anio", columns="tipo", values=["fecha", "precio_eur_mwh"])
               .to_string())
    print(f"\nResultado guardado en {RUTA_SALIDA_CCAA} y {RUTA_SALIDA_PICOS_PRECIO}")
