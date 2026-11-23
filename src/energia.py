import pandas as pd

try:                                    # python -m src.energia
    from src.territorio import PROVINCIAS
except ImportError:                     # python src/energia.py
    from territorio import PROVINCIAS

# ---------------- Configuración ----------------
CARPETA_ENTRADA = "data/raw/energia/"
RUTA_DEMANDA_CCAA = CARPETA_ENTRADA + "ree_demanda_ccaa_anual.csv"
RUTA_RENOVABLES_CCAA = CARPETA_ENTRADA + "ree_generacion_renovable_ccaa_anual.csv"
RUTA_PRECIOS = CARPETA_ENTRADA + "ree_precios_horarios.csv"   # de src/ree_precios_descarga.py
# de src/ree_ccaa_mensual_descarga.py
RUTA_DEMANDA_CCAA_MES = CARPETA_ENTRADA + "ree_demanda_ccaa_mensual.csv"
RUTA_RENOVABLES_CCAA_MES = CARPETA_ENTRADA + "ree_generacion_renovable_ccaa_mensual.csv"

RUTA_MUNICIPIOS = "data/processed/municipios.csv"      # lista maestra: codigo_ine, municipio
RUTA_PADRON = "data/raw/poblacion/ine_padron_poblacion_municipios_2016_2025.csv"

RUTA_SALIDA = "data/processed/energia_municipios.csv"

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


def limpiar_demanda_ccaa(ruta, periodo=("anio",)):
    """Demanda eléctrica por comunidad y periodo (año, o año y mes)."""
    df = pd.read_csv(ruta, encoding="utf-8")
    for col in [*periodo, "demanda_mwh"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["ccaa", *periodo, "demanda_mwh"])
    df = df[df["demanda_mwh"] > 0]
    if "meses" in df.columns:          # datos anuales: solo años completos (12 meses)
        df = df[df["meses"] == 12]
    df = normalizar_ccaa(df)
    for col in periodo:
        df[col] = df[col].astype(int)
    return df.drop_duplicates(subset=["ccaa", *periodo])[["ccaa", *periodo, "demanda_mwh"]]


def limpiar_renovables_ccaa(ruta, periodo=("anio",)):
    """Generación por comunidad y periodo, separada en renovable y no renovable."""
    df = pd.read_csv(ruta, encoding="utf-8")
    for col in [*periodo, "generacion_mwh"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["tipo"] = df["tipo"].str.strip().str.lower()
    df = df.dropna(subset=["ccaa", *periodo, "tipo", "generacion_mwh"])
    df = df[df["generacion_mwh"] >= 0]
    df = normalizar_ccaa(df)
    for col in periodo:
        df[col] = df[col].astype(int)
    df = df.drop_duplicates(subset=["ccaa", *periodo, "tipo"])

    # Una fila por comunidad y periodo, con una columna por tipo
    tabla = (df.pivot(index=["ccaa", *periodo], columns="tipo", values="generacion_mwh")
               .rename(columns={"renovable": "generacion_renovable_mwh",
                                "no renovable": "generacion_no_renovable_mwh"})
               .reset_index())
    tabla.columns.name = None
    tabla["generacion_total_mwh"] = (tabla["generacion_renovable_mwh"]
                                     + tabla["generacion_no_renovable_mwh"])
    tabla["renovable_pct"] = (tabla["generacion_renovable_mwh"]
                              / tabla["generacion_total_mwh"] * 100).round(1)
    return tabla


def unir_ccaa(demanda, renovables, periodo=("anio",)):
    """Junta demanda y generación y calcula cuánto cubre la comunidad con lo que produce."""
    df = demanda.merge(renovables, on=["ccaa", *periodo], how="outer")
    # > 100 %: la comunidad genera más de lo que consume (exporta electricidad)
    df["autoabastecimiento_pct"] = (df["generacion_total_mwh"] / df["demanda_mwh"] * 100).round(1)
    columnas = ["ccaa", *periodo, "demanda_mwh", "generacion_renovable_mwh",
                "generacion_no_renovable_mwh", "generacion_total_mwh",
                "renovable_pct", "autoabastecimiento_pct"]
    return df[columnas].sort_values(["ccaa", *periodo]).reset_index(drop=True)


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


def ccaa_por_codigo(codigos):
    """Comunidad autónoma (nombre INE) de cada código de municipio. Solo se usa por dentro
    para cruzar con REE; no sale en el CSV."""
    return codigos.str[:2].map(lambda c: PROVINCIAS.get(c, (None, None))[1])


def demanda_por_habitante(ccaa_anual, ruta_padron):
    """kWh por habitante de la comunidad: demanda de REE entre la población del padrón
    (suma de sus municipios) del mismo año, o del último disponible."""
    padron = pd.read_csv(ruta_padron, dtype={"codigo_ine": str}, encoding="utf-8-sig",
                         usecols=["codigo_ine", "anio", "poblacion"])
    padron["ccaa"] = ccaa_por_codigo(padron["codigo_ine"].str.zfill(5))
    anio = min(int(ccaa_anual["anio"].max()), int(padron["anio"].max()))
    pob = padron[padron["anio"] == anio].groupby("ccaa")["poblacion"].sum()
    return (ccaa_anual.set_index("ccaa")["demanda_mwh"] * 1000 / pob).round(0)


def reparto_por_poblacion(ccaa_anual, codigos, ruta_padron):
    """Producción, demanda y exportación ESTIMADAS de cada municipio (MWh/año).

    REE solo da estos datos por comunidad, así que se reparten de forma proporcional a la
    población del padrón del mismo año que los datos de REE (o el último):

        peso_municipio        = población_municipio / población_comunidad
        produccion_mwh        = generación_total_comunidad     * peso_municipio
        produccion_renov_mwh  = generación_renovable_comunidad * peso_municipio
        demanda_mwh           = demanda_comunidad              * peso_municipio
        exportacion_neta_mwh  = produccion_mwh - demanda_mwh   (> 0 exporta, < 0 importa)

    Se hace con funciones ya hechas de pandas:
      - groupby().transform("sum"): población de la comunidad repetida en cada municipio,
      - Series.div(): peso de cada municipio,
      - DataFrame.mul(axis=0): multiplica todas las columnas de la comunidad por el peso,
      - DataFrame.eval(): la exportación neta como resta de columnas.

    La suma de los municipios de una comunidad da exactamente el dato de REE. Como el peso
    es el mismo para producir y consumir, el signo de la exportación es el de su comunidad.
    `codigos` son los códigos INE de los municipios, en el orden de la tabla de salida."""
    padron = pd.read_csv(ruta_padron, dtype={"codigo_ine": str}, encoding="utf-8-sig",
                         usecols=["codigo_ine", "anio", "poblacion"])
    padron["codigo_ine"] = padron["codigo_ine"].str.zfill(5)
    anio = min(int(ccaa_anual["anio"].max()), int(padron["anio"].max()))

    # Una fila por municipio (en el orden de `codigos`) con su población y su comunidad
    tabla = pd.DataFrame({"codigo_ine": codigos.values})
    tabla["poblacion"] = tabla["codigo_ine"].map(
        padron[padron["anio"] == anio].set_index("codigo_ine")["poblacion"])
    tabla["ccaa"] = ccaa_por_codigo(tabla["codigo_ine"])

    # Peso = población del municipio / población de su comunidad
    peso = tabla["poblacion"].div(tabla.groupby("ccaa")["poblacion"].transform("sum"))

    # Datos de REE de su comunidad, multiplicados por el peso
    columnas = {"generacion_total_mwh": "produccion_mwh_estimada",
                "generacion_renovable_mwh": "produccion_renovable_mwh_estimada",
                "demanda_mwh": "demanda_mwh_estimada"}
    datos = tabla[["ccaa"]].join(ccaa_anual.set_index("ccaa")[list(columnas)], on="ccaa")
    res = datos[list(columnas)].mul(peso, axis=0).rename(columns=columnas)
    res = res.eval("exportacion_neta_mwh_estimada = produccion_mwh_estimada - demanda_mwh_estimada")
    return res.round(1)


def estacionalidad(ccaa_mes):
    """Mes con más demanda de cada comunidad y cuánto supera a la media mensual (%)."""
    g = ccaa_mes.groupby("ccaa")["demanda_mwh"]
    pico = ccaa_mes.loc[g.idxmax(), ["ccaa", "mes", "demanda_mwh"]].set_index("ccaa")
    return pd.DataFrame({
        "mes_demanda_maxima": pico["mes"],
        "pico_demanda_vs_media_pct": ((pico["demanda_mwh"] / g.mean() - 1) * 100).round(1),
    })


def precio_anio(picos, anio):
    """Precio de la electricidad de un año (el mismo para toda España): media anual y días
    más caro y más barato. Si ese año no está, el último disponible."""
    if anio not in set(picos["anio"]):
        anio = picos["anio"].max()
    p = picos[picos["anio"] == anio].set_index("tipo")
    return {
        "anio_precio": anio,
        "precio_medio_eur_mwh": p.loc["alto", "media_anual_eur_mwh"],
        "precio_dia_max_eur_mwh": p.loc["alto", "precio_eur_mwh"],
        "fecha_precio_max": p.loc["alto", "fecha"],
        "precio_dia_min_eur_mwh": p.loc["bajo", "precio_eur_mwh"],
        "fecha_precio_min": p.loc["bajo", "fecha"],
    }


def precio_historico(picos, dias_minimos=365):
    """Precio medio anual de la electricidad de cada año completo (el mismo para toda
    España), como columnas precio_medio_AAAA_eur_mwh. Los años con menos de
    `dias_minimos` días de datos (el año en curso) no se incluyen."""
    anual = picos.drop_duplicates("anio").set_index("anio")
    completos = anual[anual["dias_con_dato"] >= dias_minimos]
    return {f"precio_medio_{anio}_eur_mwh": fila["media_anual_eur_mwh"]
            for anio, fila in completos.sort_index().iterrows()}


def asignar_municipios(ccaa_anual, ccaa_mes, picos, ruta_municipios, ruta_padron):
    """Una fila por municipio con los indicadores de su comunidad y el precio nacional
    (el del último año con detalle y la media de todos los años completos)."""
    indicadores = ccaa_anual.set_index("ccaa")[["anio", "renovable_pct", "autoabastecimiento_pct"]]
    indicadores["demanda_kwh_habitante"] = demanda_por_habitante(ccaa_anual, ruta_padron)
    indicadores = indicadores.join(estacionalidad(ccaa_mes))

    muni = pd.read_csv(ruta_municipios, dtype={"codigo_ine": str}, encoding="utf-8-sig")
    muni["codigo_ine"] = muni["codigo_ine"].str.zfill(5)
    res = muni[["codigo_ine", "municipio"]].copy()
    res["_ccaa"] = ccaa_por_codigo(res["codigo_ine"])        # solo para cruzar, no se guarda
    res = res.join(indicadores, on="_ccaa").drop(columns="_ccaa")
    # Producción y exportación estimadas del municipio (reparto por población)
    reparto = reparto_por_poblacion(ccaa_anual, res["codigo_ine"], ruta_padron)
    posicion = res.columns.get_loc("autoabastecimiento_pct") + 1
    for i, col in enumerate(reparto.columns):
        res.insert(posicion + i, col, reparto[col].values)
    for col, valor in precio_anio(picos, int(ccaa_anual["anio"].max())).items():
        res[col] = valor
    for col, valor in precio_historico(picos).items():
        res[col] = valor
    for col in ["anio", "mes_demanda_maxima"]:
        res[col] = res[col].astype("Int64")
    sin = res["renovable_pct"].isna()
    if sin.any():
        print(f"Aviso: {sin.sum()} municipios sin datos de REE (Ceuta y Melilla no están): vacíos")
    return res


if __name__ == "__main__":
    ccaa = unir_ccaa(limpiar_demanda_ccaa(RUTA_DEMANDA_CCAA),
                     limpiar_renovables_ccaa(RUTA_RENOVABLES_CCAA))
    ccaa = ccaa[ccaa["anio"] == ccaa["anio"].max()].reset_index(drop=True)   # último año

    # Mismo dato que el anual pero mes a mes, para el mismo año
    mes = ("anio", "mes")
    ccaa_mes = unir_ccaa(limpiar_demanda_ccaa(RUTA_DEMANDA_CCAA_MES, mes),
                         limpiar_renovables_ccaa(RUTA_RENOVABLES_CCAA_MES, mes), mes)
    ccaa_mes = ccaa_mes[ccaa_mes["anio"] == ccaa["anio"].max()].reset_index(drop=True)
    meses_por_ccaa = ccaa_mes.groupby("ccaa")["mes"].nunique()
    if (meses_por_ccaa < 12).any():
        print(f"Aviso: comunidades sin los 12 meses: {meses_por_ccaa[meses_por_ccaa < 12].to_dict()}")

    picos = picos_precio(RUTA_PRECIOS)
    municipios = asignar_municipios(ccaa, ccaa_mes, picos, RUTA_MUNICIPIOS, RUTA_PADRON)
    municipios.to_csv(RUTA_SALIDA, index=False, encoding="utf-8-sig")

    print(f"Año de los datos de REE: {ccaa['anio'].max()} | {ccaa['ccaa'].nunique()} comunidades")
    print(municipios.drop_duplicates("renovable_pct").head(5).to_string(index=False))
    print(f"\nGuardado: {RUTA_SALIDA} ({len(municipios)} municipios)")
