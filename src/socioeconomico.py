import os

import pandas as pd

# ---------------- Configuración ----------------
CARPETA_ENTRADA = "data/raw/socioeconomico/"
RUTA_PARO = CARPETA_ENTRADA + "paro_municipios_sepe.csv"
RUTA_RENTA = CARPETA_ENTRADA + "ine_renta_media_municipios.csv"
RUTA_DEMOGRAFIA = CARPETA_ENTRADA + "ine_indicadores_demograficos_municipios.csv"
RUTA_MUNICIPIOS = "data/processed/municipios.csv"     # lista maestra: código y nombre únicos

RUTA_SALIDA_ANUAL = "data/processed/socioeconomico_anual.csv"
RUTA_SALIDA_MUNICIPIOS = "data/processed/socioeconomico_municipios.csv"

ANIO_INICIO = 2016
ANIO_FIN = 2025
NUM_MUNICIPIOS = 29

# Población por municipio para la tasa de paro aproximada.
# Si la ruta es None o no existe, la tasa de paro se deja vacía.
RUTA_POBLACION = None
COLUMNA_CODIGO_POBLACION = "codigo_ine"
COLUMNA_POBLACION = "poblacion"
COLUMNA_ANIO_POBLACION = None        # p.ej. "anio" si la tabla tiene varios años

# Nombres cortos de los indicadores del INE (formato largo -> columnas)
INDICADORES_RENTA = {
    "Renta neta media por persona": "renta_persona",
    "Renta neta media por hogar": "renta_hogar",
}
INDICADORES_DEMOGRAFIA = {
    "Edad media de la población": "edad_media",
    "Porcentaje de población de 65 y más años": "pct_mayores_65",
    "Porcentaje de población menor de 18 años": "pct_menores_18",
    "Tamaño medio del hogar": "tamano_hogar",
}


def codigo_ine(serie):
    """Deja el código INE como texto de 5 dígitos (recupera los ceros iniciales)."""
    return serie.astype(str).str.strip().str.zfill(5)


def leer(ruta, columna_codigo="cod_ine"):
    """Lee un CSV con el código INE como texto y lo renombra a 'codigo_ine'."""
    df = pd.read_csv(ruta, dtype={columna_codigo: str}, encoding="utf-8")
    df = df.rename(columns={columna_codigo: "codigo_ine"})
    df["codigo_ine"] = codigo_ine(df["codigo_ine"])
    return df


def cargar_datos():
    """Lee las tres fuentes socioeconómicas y la lista maestra de municipios."""
    paro = leer(RUTA_PARO)
    renta = leer(RUTA_RENTA)
    demografia = leer(RUTA_DEMOGRAFIA)
    municipios = leer(RUTA_MUNICIPIOS, "codigo_ine")[["codigo_ine", "municipio", "provincia"]]
    return paro, renta, demografia, municipios


def comprobar(df, nombre, claves, municipios):
    """Avisa de duplicados, nulos y municipios que faltan o sobran; quita los duplicados."""
    duplicados = df.duplicated(subset=claves).sum()
    if duplicados:
        print(f"Aviso [{nombre}]: {duplicados} filas duplicadas en {claves} (se quita la repetida)")
        df = df.drop_duplicates(subset=claves)

    nulos = df.isna().sum()
    if nulos.any():
        print(f"Aviso [{nombre}]: valores nulos -> {nulos[nulos > 0].to_dict()}")

    esperados = set(municipios["codigo_ine"])
    encontrados = set(df["codigo_ine"])
    if len(encontrados) != NUM_MUNICIPIOS:
        print(f"Aviso [{nombre}]: {len(encontrados)} municipios en vez de {NUM_MUNICIPIOS}")
    if esperados - encontrados:
        print(f"Aviso [{nombre}]: faltan los códigos {sorted(esperados - encontrados)}")
    if encontrados - esperados:
        print(f"Aviso [{nombre}]: códigos que no están en {RUTA_MUNICIPIOS}: "
              f"{sorted(encontrados - esperados)}")
    return df


def filtrar_periodo(df):
    """Se queda con los años entre ANIO_INICIO y ANIO_FIN."""
    df["anio"] = pd.to_numeric(df["anio"], errors="coerce")
    df = df[df["anio"].between(ANIO_INICIO, ANIO_FIN)].copy()
    df["anio"] = df["anio"].astype(int)
    return df


def limpiar_paro(df, municipios):
    """Paro registrado (SEPE): medio anual, diciembre y nº de meses con dato."""
    df = filtrar_periodo(df)
    for col in ["paro_medio_anual", "paro_diciembre", "meses"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = comprobar(df, "paro", ["codigo_ine", "anio"], municipios)
    incompletos = sorted(int(a) for a in df.loc[df["meses"] < 12, "anio"].unique())
    if incompletos:
        print(f"Nota [paro]: años con menos de 12 meses (media de los meses disponibles): "
              f"{incompletos}")
    df = df.rename(columns={"meses": "meses_paro"})
    return df[["codigo_ine", "anio", "paro_medio_anual", "paro_diciembre", "meses_paro"]]


def largo_a_ancho(df, columna_valor, indicadores, nombre, municipios):
    """Pasa un CSV del INE de formato largo (una fila por indicador) a una columna por indicador."""
    df = filtrar_periodo(df)
    df["indicador"] = df["indicador"].str.strip()
    desconocidos = set(df["indicador"]) - set(indicadores)
    if desconocidos:
        print(f"Aviso [{nombre}]: indicadores no previstos (se ignoran): {sorted(desconocidos)}")
    df = df[df["indicador"].isin(indicadores)].copy()
    df["indicador"] = df["indicador"].map(indicadores)
    df[columna_valor] = pd.to_numeric(df[columna_valor], errors="coerce")
    df = comprobar(df, nombre, ["codigo_ine", "anio", "indicador"], municipios)

    ancho = (df.pivot(index=["codigo_ine", "anio"], columns="indicador", values=columna_valor)
               .reset_index())
    ancho.columns.name = None
    return ancho[["codigo_ine", "anio"] + list(indicadores.values())]


def unir_anual(municipios, paro, renta, demografia):
    """Una fila por municipio y año del periodo. Lo que no exista en una fuente queda vacío."""
    rejilla = pd.MultiIndex.from_product(
        [municipios["codigo_ine"], range(ANIO_INICIO, ANIO_FIN + 1)],
        names=["codigo_ine", "anio"]).to_frame(index=False)
    df = (rejilla.merge(municipios, on="codigo_ine", how="left")
                 .merge(paro, on=["codigo_ine", "anio"], how="left")
                 .merge(renta, on=["codigo_ine", "anio"], how="left")
                 .merge(demografia, on=["codigo_ine", "anio"], how="left"))
    enteros = ["paro_medio_anual", "paro_diciembre", "meses_paro"] + list(INDICADORES_RENTA.values())
    for col in enteros:
        df[col] = df[col].round().astype("Int64")   # enteros que admiten vacío
    return df.sort_values(["codigo_ine", "anio"]).reset_index(drop=True)


def ultimo_dato(anual, columnas, sufijo_anio):
    """Para cada municipio, el último año con dato en columnas[0] y sus valores."""
    datos = anual.dropna(subset=[columnas[0]])
    ultimo = datos.loc[datos.groupby("codigo_ine")["anio"].idxmax(),
                       ["codigo_ine", "anio"] + columnas]
    return ultimo.rename(columns={"anio": f"anio_{sufijo_anio}"})


def variacion_pct(anual, columna, nombre):
    """Variación en % entre el primer y el último año con dato de cada municipio."""
    datos = anual.dropna(subset=[columna]).sort_values("anio")
    extremos = datos.groupby("codigo_ine")[columna].agg(["first", "last"])
    resultado = ((extremos["last"] - extremos["first"]) / extremos["first"] * 100).round(1)
    return resultado.rename(nombre).reset_index()


def cargar_poblacion():
    """Población por municipio (la del año más reciente si la tabla tiene varios)."""
    if not RUTA_POBLACION or not os.path.exists(RUTA_POBLACION):
        print("Aviso: no hay tabla de población por municipio -> tasa_paro_aprox vacía "
              "(configura RUTA_POBLACION)")
        return None
    df = leer(RUTA_POBLACION, COLUMNA_CODIGO_POBLACION)
    df["poblacion"] = pd.to_numeric(df[COLUMNA_POBLACION], errors="coerce")
    if COLUMNA_ANIO_POBLACION:
        df = df.sort_values(COLUMNA_ANIO_POBLACION).drop_duplicates("codigo_ine", keep="last")
        df = df.rename(columns={COLUMNA_ANIO_POBLACION: "anio_poblacion"})
    else:
        df["anio_poblacion"] = pd.NA
    return df[["codigo_ine", "poblacion", "anio_poblacion"]]


def calcular_municipios(anual, municipios):
    """Una fila por municipio: último dato de cada fuente, variaciones y tasa de paro."""
    paro = ultimo_dato(anual, ["paro_medio_anual", "paro_diciembre"], "paro")
    renta = ultimo_dato(anual, list(INDICADORES_RENTA.values()), "renta")
    demografia = ultimo_dato(anual, list(INDICADORES_DEMOGRAFIA.values()), "demografia")

    df = (municipios.merge(paro, on="codigo_ine", how="left")
                    .merge(renta, on="codigo_ine", how="left")
                    .merge(demografia, on="codigo_ine", how="left")
                    .merge(variacion_pct(anual, "paro_medio_anual", "var_paro_pct"),
                           on="codigo_ine", how="left")
                    .merge(variacion_pct(anual, "renta_persona", "var_renta_persona_pct"),
                           on="codigo_ine", how="left"))

    poblacion = cargar_poblacion()
    if poblacion is not None:
        df = df.merge(poblacion, on="codigo_ine", how="left")
        # Aproximada: divide parados entre TODA la población, no entre la población activa
        df["tasa_paro_aprox"] = (df["paro_medio_anual"] / df["poblacion"] * 100).round(2)
    else:
        df["poblacion"] = pd.NA
        df["anio_poblacion"] = pd.NA
        df["tasa_paro_aprox"] = pd.NA

    columnas = (["codigo_ine", "municipio", "provincia",
                 "anio_paro", "paro_medio_anual", "paro_diciembre", "var_paro_pct",
                 "poblacion", "anio_poblacion", "tasa_paro_aprox",
                 "anio_renta"] + list(INDICADORES_RENTA.values()) + ["var_renta_persona_pct",
                 "anio_demografia"] + list(INDICADORES_DEMOGRAFIA.values()))
    return df[columnas].sort_values("renta_persona", ascending=False).reset_index(drop=True)


def anios_cubiertos(df, columna):
    """Primer y último año con dato de una columna, como texto."""
    anios = df.dropna(subset=[columna])["anio"]
    return f"{anios.min()}-{anios.max()}" if len(anios) else "sin datos"


if __name__ == "__main__":
    paro_bruto, renta_bruta, demografia_bruta, municipios = cargar_datos()
    municipios = municipios.drop_duplicates("codigo_ine")

    paro = limpiar_paro(paro_bruto, municipios)
    renta = largo_a_ancho(renta_bruta, "valor_eur", INDICADORES_RENTA, "renta", municipios)
    demografia = largo_a_ancho(demografia_bruta, "valor", INDICADORES_DEMOGRAFIA,
                               "demografía", municipios)

    anual = unir_anual(municipios, paro, renta, demografia)
    resumen = calcular_municipios(anual, municipios)

    anual.to_csv(RUTA_SALIDA_ANUAL, index=False, encoding="utf-8-sig")
    resumen.to_csv(RUTA_SALIDA_MUNICIPIOS, index=False, encoding="utf-8-sig")

    print(f"\nMunicipios: {anual['codigo_ine'].nunique()} | periodo {ANIO_INICIO}-{ANIO_FIN} "
          f"| filas anuales: {len(anual)}")
    print(f"Años cubiertos -> paro: {anios_cubiertos(anual, 'paro_medio_anual')} | "
          f"renta: {anios_cubiertos(anual, 'renta_persona')} | "
          f"demografía: {anios_cubiertos(anual, 'edad_media')}")

    columnas = ["municipio", "anio_renta", "renta_persona", "var_renta_persona_pct",
                "paro_medio_anual", "var_paro_pct", "tasa_paro_aprox"]
    print("\n5 municipios con MÁS renta por persona:")
    print(resumen.head(5)[columnas].to_string(index=False))
    print("\n5 municipios con MENOS renta por persona:")
    print(resumen.tail(5)[columnas].to_string(index=False))
    print(f"\nResultado guardado en {RUTA_SALIDA_ANUAL} y {RUTA_SALIDA_MUNICIPIOS}")
