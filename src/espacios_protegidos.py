import pandas as pd

# ---------------- Configuración ----------------
RUTA_ENTRADA = "data/raw/medioambiente/eea_natura2000_espacios_cercanos_municipios.csv"
RUTA_MUNICIPIOS = "data/processed/municipios.csv"      # lista maestra: codigo_ine, municipio, latitud, longitud

RUTA_SALIDA_ESPACIOS = "data/processed/espacios_protegidos_limpio.csv"
RUTA_SALIDA_MUNICIPIOS = "data/processed/espacios_protegidos_municipios.csv"

# El CSV de origen trae los espacios Red Natura 2000 a menos de 25 km del centro de cada
# municipio. La distancia se midió hasta el borde del polígono (0 = el centro está dentro).
RADIO_MAX_KM = 25
RADIOS_KM = [5, 10, 25]
DISTANCIA_SEGURA_KM = 10          # a partir de aquí se considera que no condiciona el CPD
MARINO_MIN_PCT = 50               # espacio "marino" si más de la mitad de su superficie es mar

# Tipos de espacio de la Red Natura 2000
TIPOS = {
    "A": "ZEPA (Directiva Aves)",
    "B": "LIC/ZEC (Directiva Hábitats)",
    "C": "ZEPA y LIC/ZEC",
}
# Si falta el % marino, se deduce por el código (ESZZ = espacios marinos) o por el nombre
PALABRAS_MARINO = r"marin|submarin|corredor migratorio|sebadal|fondos marinos|bahía de"


def cargar_datos(ruta):
    """Lee los espacios Red Natura 2000 cercanos a cada municipio (EEA, versión 2024)."""
    df = pd.read_csv(ruta, dtype={"codigo_ine": str, "sitecode": str}, encoding="utf-8")
    for col in ["area_ha", "pct_area_marina", "distancia_km"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


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

    print(f"Filas: {filas_inicio} leídas -> {len(df)} limpias "
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

    sin_datos = set(muni["codigo_ine"]) - set(espacios["codigo_ine"])
    if sin_datos:
        print(f"Aviso: municipios sin ningún espacio en {RADIO_MAX_KM} km: {sorted(sin_datos)}")
    return res.sort_values("puntuacion_ambiental", ascending=False).reset_index(drop=True)


if __name__ == "__main__":
    espacios = limpiar(cargar_datos(RUTA_ENTRADA))
    municipios = resumir_municipios(espacios, RUTA_MUNICIPIOS)

    espacios.to_csv(RUTA_SALIDA_ESPACIOS, index=False, encoding="utf-8-sig")
    municipios.to_csv(RUTA_SALIDA_MUNICIPIOS, index=False, encoding="utf-8-sig")

    columnas = ["municipio", "dist_min_km", "espacio_mas_cercano", "n_espacios_10km",
                "riesgo_ambiental", "puntuacion_ambiental"]
    print(f"\nMunicipios ordenados por puntuación ambiental (100 = sin condicionantes):")
    print(municipios[columnas].to_string(index=False))
    print(f"\nGuardado: {RUTA_SALIDA_ESPACIOS}, {RUTA_SALIDA_MUNICIPIOS}")
