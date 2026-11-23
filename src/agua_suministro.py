import pandas as pd

try:                                    # python -m src.agua_suministro
    from src.territorio import PROVINCIAS
except ImportError:                     # python src/agua_suministro.py
    from territorio import PROVINCIAS

# ---------------- Configuración ----------------
RUTA_ENTRADA = "data/raw/agua/ine_suministro_agua_ccaa_2016_2024.csv"
RUTA_PADRON = "data/raw/poblacion/ine_padron_poblacion_municipios_2016_2025.csv"
RUTA_MUNICIPIOS = "data/processed/municipios.csv"      # lista maestra: codigo_ine, municipio

RUTA_SALIDA_MUNICIPIOS = "data/processed/agua_suministro_municipios.csv"

# Volúmenes del INE en miles de m3 -> litros (1 m3 = 1.000 L)
LITROS_POR_MILES_M3 = 1_000_000
PERDIDAS_MAX_PCT = 50                   # más pérdidas que esto sobre lo suministrado es sospechoso

# Nombres del INE en esta tabla -> nombres que usa el resto del proyecto (energia.py, territorio.py)
NOMBRES_CCAA = {
    "Castilla-La Mancha": "Castilla - La Mancha",
}

COLUMNAS_NUMERICAS = [
    "agua_suministrada_red_miles_m3", "perdidas_reales_miles_m3", "agua_distribuida_total_miles_m3",
    "agua_sectores_economicos_miles_m3", "agua_hogares_miles_m3", "importe_facturado_miles_eur",
    "coste_unitario_eur_m3", "perdidas_reales_m3_km_anio",
]


def cargar_datos(ruta):
    """Lee la tabla del INE de suministro y saneamiento del agua por comunidades."""
    df = pd.read_csv(ruta, encoding="utf-8")
    for col in ["anio"] + COLUMNAS_NUMERICAS:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def limpiar(df):
    """Normaliza nombres, quita duplicados y valores imposibles, y separa el total de España."""
    filas_inicio = len(df)
    df = df.dropna(subset=["ccaa", "anio"]).copy()
    df["ccaa"] = df["ccaa"].str.strip().replace(NOMBRES_CCAA)
    df["anio"] = df["anio"].astype(int)
    df = df.drop_duplicates(subset=["ccaa", "anio"], keep="last")

    # Valores imposibles -> NaN (no se borra la fila entera, el resto de columnas vale)
    for col in COLUMNAS_NUMERICAS:
        negativos = df[col] < 0
        if negativos.any():
            print(f"Aviso: {negativos.sum()} valores negativos en {col} -> vacío")
            df.loc[negativos, col] = pd.NA
    malos = df["perdidas_reales_miles_m3"] > df["agua_suministrada_red_miles_m3"]
    malos |= df["agua_distribuida_total_miles_m3"] > df["agua_suministrada_red_miles_m3"]
    if malos.any():
        print(f"Aviso: {malos.sum()} filas con volúmenes incoherentes:")
        print(df.loc[malos, ["ccaa", "anio"]].to_string(index=False))

    df["ambito"] = df["ccaa"].map(lambda c: "nacional" if c == "España" else "ccaa")
    print(f"Filas: {filas_inicio} leídas -> {len(df)} limpias "
          f"({df['ccaa'].nunique() - 1} comunidades + España, años {sorted(df['anio'].unique().tolist())})")
    return df.sort_values(["ambito", "ccaa", "anio"]).reset_index(drop=True)


def poblacion_ccaa(ruta_padron):
    """Población por comunidad y año sumando el padrón municipal.

    Ceuta y Melilla se juntan porque el INE las publica juntas en la tabla de agua.
    """
    padron = pd.read_csv(ruta_padron, dtype={"codigo_ine": str}, encoding="utf-8-sig",
                         usecols=["codigo_ine", "anio", "poblacion"])
    padron["poblacion"] = pd.to_numeric(padron["poblacion"], errors="coerce")
    padron["ccaa"] = padron["codigo_ine"].str.zfill(5).str[:2].map(
        lambda c: PROVINCIAS.get(c, (None, None))[1])
    padron["ccaa"] = padron["ccaa"].replace({"Ceuta": "Ceuta y Melilla", "Melilla": "Ceuta y Melilla"})
    pob = padron.dropna(subset=["ccaa"]).groupby(["ccaa", "anio"], as_index=False)["poblacion"].sum()
    espana = pob.groupby("anio", as_index=False)["poblacion"].sum().assign(ccaa="España")
    return pd.concat([pob, espana], ignore_index=True)


def calcular(df, poblacion):
    """Indicadores comparables entre comunidades: % pérdidas, litros/hab/día y evolución."""
    df = df.merge(poblacion, on=["ccaa", "anio"], how="left")
    sin_pob = df[df["poblacion"].isna()]
    if len(sin_pob):
        print(f"Aviso: sin población para {sorted(set(sin_pob['ccaa']))}")

    dias = df["anio"].map(lambda a: 366 if pd.Timestamp(a, 12, 31).is_leap_year else 365)
    por_hab_dia = LITROS_POR_MILES_M3 / (df["poblacion"] * dias)
    df["pct_perdidas_reales"] = (df["perdidas_reales_miles_m3"] / df["agua_suministrada_red_miles_m3"]
                                 * 100).round(2)
    df["pct_uso_economico"] = (df["agua_sectores_economicos_miles_m3"] / df["agua_distribuida_total_miles_m3"]
                               * 100).round(2)
    # El INE calcula unos 128 L/hab/día para España en 2022-2024 (con población a 1 de julio;
    # aquí se usa el padrón a 1 de enero, así que puede haber 1-2 litros de diferencia)
    df["consumo_hogares_l_hab_dia"] = (df["agua_hogares_miles_m3"] * por_hab_dia).round(1)
    df["suministro_total_l_hab_dia"] = (df["agua_suministrada_red_miles_m3"] * por_hab_dia).round(1)

    altas = df[df["pct_perdidas_reales"] > PERDIDAS_MAX_PCT]
    if len(altas):
        print(f"Aviso: pérdidas > {PERDIDAS_MAX_PCT}% en {list(zip(altas['ccaa'], altas['anio']))}")

    # Evolución del agua suministrada respecto a la medición anterior (cada 2 años)
    df = df.sort_values(["ccaa", "anio"])
    df["var_suministro_pct"] = (df.groupby("ccaa")["agua_suministrada_red_miles_m3"].pct_change()
                                * 100).round(2)
    return df.reset_index(drop=True)


def asignar_municipios(anual, ruta_municipios):
    """Cada municipio de la lista maestra recibe los indicadores de su comunidad (último año)
    y la media de todos los años, para suavizar años raros. La comunidad solo se usa por
    dentro para cruzar (sale de las 2 primeras cifras del código INE): no se guarda."""
    ccaa = anual[anual["ambito"] == "ccaa"]
    ultimo = ccaa["anio"].max()
    indicadores = ["coste_unitario_eur_m3", "pct_perdidas_reales", "perdidas_reales_m3_km_anio",
                   "consumo_hogares_l_hab_dia", "suministro_total_l_hab_dia", "pct_uso_economico"]
    actual = ccaa[ccaa["anio"] == ultimo][["ccaa"] + indicadores]
    media = ccaa.groupby("ccaa")[indicadores].mean().round(2).add_suffix("_media").reset_index()

    muni = pd.read_csv(ruta_municipios, dtype={"codigo_ine": str}, encoding="utf-8-sig")
    muni["codigo_ine"] = muni["codigo_ine"].str.zfill(5)
    muni["ccaa"] = muni["codigo_ine"].str[:2].map(lambda c: PROVINCIAS.get(c, (None, None))[1])
    muni["ccaa"] = muni["ccaa"].replace({"Ceuta": "Ceuta y Melilla", "Melilla": "Ceuta y Melilla"})
    res = muni[["codigo_ine", "municipio", "ccaa"]].merge(actual, on="ccaa", how="left")
    res = res.merge(media, on="ccaa", how="left").drop(columns="ccaa")
    res.insert(2, "anio", ultimo)
    sin_dato = res[res["coste_unitario_eur_m3"].isna()]
    if len(sin_dato):
        print(f"Aviso: municipios sin datos de agua: {list(sin_dato['municipio'])}")
    return res


if __name__ == "__main__":
    anual = calcular(limpiar(cargar_datos(RUTA_ENTRADA)), poblacion_ccaa(RUTA_PADRON))
    municipios = asignar_municipios(anual, RUTA_MUNICIPIOS)
    # La tabla por comunidad solo se usa por dentro: el proyecto trabaja por municipio
    municipios.to_csv(RUTA_SALIDA_MUNICIPIOS, index=False, encoding="utf-8-sig")

    ultimo = anual[anual["anio"] == anual["anio"].max()]
    columnas = ["ccaa", "coste_unitario_eur_m3", "pct_perdidas_reales", "consumo_hogares_l_hab_dia",
                "suministro_total_l_hab_dia"]
    print(f"\nAño {anual['anio'].max()} por coste del agua:")
    print(ultimo.sort_values("coste_unitario_eur_m3")[columnas].to_string(index=False))
    print(f"\nGuardado: {RUTA_SALIDA_MUNICIPIOS} ({len(municipios)} municipios)")
