import pandas as pd

# ---------------- Configuración ----------------
CARPETA_ENTRADA = "data/raw/energia/"
RUTA_DEMANDA_CCAA = CARPETA_ENTRADA + "ree_demanda_ccaa_anual.csv"
RUTA_RENOVABLES_CCAA = CARPETA_ENTRADA + "ree_generacion_renovable_ccaa_anual.csv"
RUTA_DEMANDA_NACIONAL = CARPETA_ENTRADA + "ree_demanda_nacional_mensual.csv"
RUTA_CO2_NACIONAL = CARPETA_ENTRADA + "ree_emisiones_co2_mensual.csv"

RUTA_SALIDA_CCAA = "data/processed/energia_ccaa_anual.csv"
RUTA_SALIDA_NACIONAL = "data/processed/energia_nacional_mensual.csv"

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


def limpiar_mensual(ruta, columna):
    """Serie nacional mensual (fecha AAAA-MM + un valor)."""
    df = pd.read_csv(ruta, encoding="utf-8")
    df["fecha"] = pd.to_datetime(df["fecha"], format="%Y-%m", errors="coerce")
    df[columna] = pd.to_numeric(df[columna], errors="coerce")
    df = df.dropna(subset=["fecha", columna])
    df = df[df[columna] > 0]
    return df.drop_duplicates(subset=["fecha"])[["fecha", columna]]


def unir_nacional(demanda, co2):
    """Demanda y emisiones de CO₂ del sistema eléctrico, mes a mes."""
    df = demanda.merge(co2, on="fecha", how="outer").sort_values("fecha")
    df["anio"] = df["fecha"].dt.year
    df["mes"] = df["fecha"].dt.month
    df["fecha"] = df["fecha"].dt.strftime("%Y-%m")
    return df[["fecha", "anio", "mes", "demanda_mwh", "emisiones_tco2"]].reset_index(drop=True)


if __name__ == "__main__":
    ccaa = unir_ccaa(limpiar_demanda_ccaa(RUTA_DEMANDA_CCAA),
                     limpiar_renovables_ccaa(RUTA_RENOVABLES_CCAA))
    nacional = unir_nacional(limpiar_mensual(RUTA_DEMANDA_NACIONAL, "demanda_mwh"),
                             limpiar_mensual(RUTA_CO2_NACIONAL, "emisiones_tco2"))

    ccaa.to_csv(RUTA_SALIDA_CCAA, index=False, encoding="utf-8-sig")
    nacional.to_csv(RUTA_SALIDA_NACIONAL, index=False, encoding="utf-8-sig")

    ultimo = ccaa["anio"].max()
    print(f"Comunidades: {ccaa['ccaa'].nunique()} | años {ccaa['anio'].min()}-{ultimo} "
          f"| filas: {len(ccaa)}")
    print(f"Meses nacionales: {len(nacional)} ({nacional['fecha'].iloc[0]} -> "
          f"{nacional['fecha'].iloc[-1]})")
    huecos = ccaa.isna().sum().sum() + nacional.isna().sum().sum()
    if huecos:
        print(f"Aviso: {huecos} valores vacíos tras unir las tablas")

    print(f"\n% renovable y autoabastecimiento por comunidad en {ultimo}:")
    print(ccaa[ccaa["anio"] == ultimo]
          .sort_values("renovable_pct", ascending=False)
          [["ccaa", "demanda_mwh", "generacion_total_mwh", "renovable_pct",
            "autoabastecimiento_pct"]]
          .to_string(index=False))

    anual = nacional.groupby("anio")[["demanda_mwh", "emisiones_tco2"]].sum()
    print("\nTotales nacionales por año (MWh y t CO₂):")
    print(anual.round(0).to_string())
    print(f"\nResultado guardado en {RUTA_SALIDA_CCAA} y {RUTA_SALIDA_NACIONAL}")
