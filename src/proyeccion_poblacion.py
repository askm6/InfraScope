import pandas as pd

try:                                    # python -m src.proyeccion_poblacion
    from src.territorio import PROVINCIAS, CODIGO_POR_PROVINCIA
except ImportError:                     # python src/proyeccion_poblacion.py
    from territorio import PROVINCIAS, CODIGO_POR_PROVINCIA

# ---------------- Configuración ----------------
RUTA_ENTRADA = "data/raw/poblacion/ine_proyeccion_poblacion_provincias_2026_2041.csv"
RUTA_MUNICIPIOS = "data/processed/municipios.csv"      # lista maestra: codigo_ine, municipio
RUTA_PADRON = "data/raw/poblacion/ine_padron_poblacion_municipios_2016_2025.csv"

RUTA_SALIDA_MUNICIPIOS = "data/processed/proyeccion_poblacion_municipios.csv"

HORIZONTE_ANIOS = 10                    # el enunciado pide previsiones a 10 años
VARIACION_ANUAL_MAX_PCT = 5             # un salto mayor de un año a otro se considera sospechoso


def cargar_datos(ruta):
    """Lee la proyección de población del INE (tabla 36725, corto plazo)."""
    df = pd.read_csv(ruta, encoding="utf-8", dtype={"provincia": str})
    df["anio"] = pd.to_numeric(df["anio"], errors="coerce")
    df["poblacion_proyectada"] = pd.to_numeric(df["poblacion_proyectada"], errors="coerce")
    return df


def limpiar(df):
    """Quita filas inválidas y duplicados, separa el total nacional y añade códigos."""
    filas_inicio = len(df)
    df = df.dropna(subset=["provincia", "anio", "poblacion_proyectada"]).copy()
    df["provincia"] = df["provincia"].str.strip()
    df = df[df["poblacion_proyectada"] > 0]
    df["anio"] = df["anio"].astype(int)
    df["poblacion_proyectada"] = df["poblacion_proyectada"].round().astype(int)
    df = df.drop_duplicates(subset=["provincia", "anio"], keep="last")

    nacional = df[df["provincia"] == "Total Nacional"]
    df = df[df["provincia"] != "Total Nacional"].copy()

    # Nombre INE -> código de provincia y comunidad autónoma
    desconocidas = set(df["provincia"]) - set(CODIGO_POR_PROVINCIA)
    if desconocidas:
        print(f"Aviso: provincias sin código (se descartan): {sorted(desconocidas)}")
    df["codigo_provincia"] = df["provincia"].map(CODIGO_POR_PROVINCIA)
    df = df.dropna(subset=["codigo_provincia"])
    df["ccaa"] = df["codigo_provincia"].map(lambda c: PROVINCIAS[c][1])

    # Comprobaciones: todas las provincias con la serie completa y la suma ≈ total nacional
    anios = sorted(df["anio"].unique())
    incompletas = df.groupby("provincia")["anio"].nunique()
    incompletas = incompletas[incompletas < len(anios)]
    if len(incompletas):
        print(f"Aviso: provincias con años que faltan: {list(incompletas.index)}")
    if len(nacional):
        suma = df.groupby("anio")["poblacion_proyectada"].sum()
        dif = (suma - nacional.set_index("anio")["poblacion_proyectada"]).abs().max()
        print(f"Diferencia máx. entre suma de provincias y total nacional: {dif:,} hab.")

    print(f"Filas: {filas_inicio} leídas -> {len(df)} limpias ({df['provincia'].nunique()} provincias, "
          f"{anios[0]}-{anios[-1]})")
    columnas = ["codigo_provincia", "provincia", "ccaa", "anio", "poblacion_proyectada"]
    return df.sort_values(["codigo_provincia", "anio"])[columnas].reset_index(drop=True)


def calcular_anual(df):
    """Variación anual y crecimiento acumulado respecto al primer año de la proyección."""
    df = df.copy()
    g = df.groupby("codigo_provincia")["poblacion_proyectada"]
    df["var_anual_pct"] = (g.pct_change() * 100).round(3)
    df["crec_acumulado_pct"] = ((df["poblacion_proyectada"] / g.transform("first") - 1) * 100).round(2)

    raros = df[df["var_anual_pct"].abs() > VARIACION_ANUAL_MAX_PCT]
    if len(raros):
        print(f"Aviso: {len(raros)} saltos anuales > {VARIACION_ANUAL_MAX_PCT}%:")
        print(raros.to_string(index=False))
    return df


def resumen_provincias(anual, horizonte=HORIZONTE_ANIOS):
    """Una fila por provincia: población inicial, a N años y al final, y su crecimiento."""
    anio_ini = anual["anio"].min()
    anio_hor = min(anio_ini + horizonte, anual["anio"].max())
    anio_fin = anual["anio"].max()

    tabla = anual.pivot_table(index=["codigo_provincia", "provincia", "ccaa"],
                              columns="anio", values="poblacion_proyectada").reset_index()
    res = tabla[["codigo_provincia", "provincia", "ccaa"]].copy()
    res[f"poblacion_{anio_ini}"] = tabla[anio_ini].astype(int)
    res[f"poblacion_{anio_hor}"] = tabla[anio_hor].astype(int)
    res[f"poblacion_{anio_fin}"] = tabla[anio_fin].astype(int)
    res[f"crec_{horizonte}a_pct"] = ((tabla[anio_hor] / tabla[anio_ini] - 1) * 100).round(2)
    res["crec_total_pct"] = ((tabla[anio_fin] / tabla[anio_ini] - 1) * 100).round(2)
    # Tasa de crecimiento anual compuesta (CAGR) en el horizonte
    res["tasa_anual_media_pct"] = (((tabla[anio_hor] / tabla[anio_ini]) ** (1 / (anio_hor - anio_ini)) - 1)
                                   * 100).round(3)
    res["tendencia"] = pd.cut(res[f"crec_{horizonte}a_pct"], bins=[-100, -1, 1, 100],
                              labels=["decrece", "estable", "crece"])
    res = res.sort_values(f"crec_{horizonte}a_pct", ascending=False).reset_index(drop=True)
    res.insert(0, "ranking_crecimiento", range(1, len(res) + 1))
    return res


def asignar_municipios(resumen, anual, ruta_municipios, ruta_padron):
    """Proyección por municipio, con una columna poblacion_AAAA por CADA año de la
    proyección del INE (de `anual`). El INE solo proyecta provincias, así que cada municipio
    conserva el peso que tiene en su provincia según el padrón del último año:
    poblacion_municipio_año = poblacion_provincia_proyectada_año * (padrón municipio / padrón provincia).
    Los crecimientos (%) y la tendencia son los de su provincia (de `resumen`). La provincia
    solo se usa por dentro para cruzar (2 primeras cifras del código INE); no sale en el CSV."""
    muni = pd.read_csv(ruta_municipios, dtype={"codigo_ine": str}, encoding="utf-8-sig")
    muni["codigo_ine"] = muni["codigo_ine"].str.zfill(5)
    padron = pd.read_csv(ruta_padron, dtype={"codigo_ine": str}, encoding="utf-8-sig",
                         usecols=["codigo_ine", "anio", "poblacion"])
    anio_padron = int(padron["anio"].max())
    padron = padron[padron["anio"] == anio_padron].set_index("codigo_ine")["poblacion"]

    res = muni[["codigo_ine", "municipio"]].copy()
    res[f"poblacion_padron_{anio_padron}"] = res["codigo_ine"].map(padron).astype("Int64")
    cod_prov = res["codigo_ine"].str[:2]
    peso = res[f"poblacion_padron_{anio_padron}"] / padron.groupby(padron.index.str[:2]).sum().reindex(cod_prov).values
    # Población provincial de cada año (una columna por año) -> la del municipio
    por_anio = anual.pivot(index="codigo_provincia", columns="anio",
                           values="poblacion_proyectada").reindex(cod_prov)
    for anio in sorted(por_anio.columns):
        res[f"poblacion_{anio}"] = (por_anio[anio].values * peso).round().astype("Int64")
    prov = resumen.set_index("codigo_provincia").reindex(cod_prov)
    for col in [c for c in resumen.columns if c.startswith(("crec_", "tasa_", "tendencia"))]:
        res[col] = prov[col].values
    sin_dato = res[res[f"poblacion_padron_{anio_padron}"].isna()]
    if len(sin_dato):
        print(f"Aviso: {len(sin_dato)} municipios sin padrón (proyección vacía): {list(sin_dato['municipio'])[:10]}")
    return res


if __name__ == "__main__":
    # Las tablas provinciales solo se usan por dentro: el proyecto trabaja por municipio
    anual = calcular_anual(limpiar(cargar_datos(RUTA_ENTRADA)))
    resumen = resumen_provincias(anual)
    municipios = asignar_municipios(resumen, anual, RUTA_MUNICIPIOS, RUTA_PADRON)
    municipios.to_csv(RUTA_SALIDA_MUNICIPIOS, index=False, encoding="utf-8-sig")

    columna = f"crec_{HORIZONTE_ANIOS}a_pct"
    print(f"\nMunicipios grandes ordenados por crecimiento a {HORIZONTE_ANIOS} años:")
    print(municipios.nlargest(300, municipios.columns[2]).sort_values(columna, ascending=False)
          .head(8).to_string(index=False))
    print(f"\nGuardado: {RUTA_SALIDA_MUNICIPIOS} ({len(municipios)} municipios)")
