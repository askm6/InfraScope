"""Población por municipio: data/processed/poblacion_municipios.csv.

Origen: padrón municipal del INE, 2016-2025
(data/raw/poblacion/ine_padron_poblacion_municipios_2016_2025.csv).
Una fila por municipio de la lista maestra con la población del último año, su peso en
España, su puesto y la evolución desde el primer año del padrón.
"""
import pandas as pd

# ---------------- Configuración ----------------
RUTA_ENTRADA = "data/raw/poblacion/ine_padron_poblacion_municipios_2016_2025.csv"
RUTA_MUNICIPIOS = "data/processed/municipios.csv"      # lista maestra: codigo_ine, municipio
RUTA_SALIDA = "data/processed/poblacion_municipios.csv"
ANIO = None                     # None = el último año del padrón


def cargar_datos(ruta):
    """Lee el padrón (una fila por municipio y año) con el código INE como texto."""
    df = pd.read_csv(ruta, dtype={"codigo_ine": str}, encoding="utf-8-sig")
    df["codigo_ine"] = df["codigo_ine"].str.strip().str.zfill(5)
    for col in ["anio", "poblacion", "hombres", "mujeres"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.dropna(subset=["anio"]).astype({"anio": int})


def limpiar(df):
    """Quita duplicados (municipio, año) y poblaciones imposibles (<= 0 -> vacío)."""
    duplicados = df.duplicated(["codigo_ine", "anio"]).sum()
    if duplicados:
        print(f"Aviso: {duplicados} filas repetidas (municipio, año): se quita la repetida")
        df = df.drop_duplicates(["codigo_ine", "anio"], keep="last")
    malos = df["poblacion"] <= 0
    if malos.any():
        print(f"Aviso: {malos.sum()} poblaciones <= 0 -> vacío")
        df.loc[malos, "poblacion"] = pd.NA
    return df


def calcular(padron, ruta_municipios, anio=None):
    """Una fila por municipio de la lista maestra: población del año elegido, % sobre
    España, puesto (1 = el más poblado) y variación desde el primer año del padrón."""
    anio = anio or int(padron["anio"].max())
    anio_ini = int(padron["anio"].min())
    actual = padron[padron["anio"] == anio].set_index("codigo_ine")
    inicial = padron[padron["anio"] == anio_ini].set_index("codigo_ine")["poblacion"]

    muni = pd.read_csv(ruta_municipios, dtype={"codigo_ine": str}, encoding="utf-8-sig")
    res = muni[["codigo_ine", "municipio"]].copy()
    res["anio"] = anio
    res = res.join(actual[["poblacion", "hombres", "mujeres"]], on="codigo_ine")
    res["pct_espana"] = (res["poblacion"] / actual["poblacion"].sum() * 100).round(4)
    res["ranking"] = res["poblacion"].rank(ascending=False, method="min").astype("Int64")
    res[f"var_{anio_ini}_{anio}_pct"] = ((res["poblacion"] / res["codigo_ine"].map(inicial) - 1)
                                         * 100).round(2)
    for col in ["poblacion", "hombres", "mujeres"]:
        res[col] = res[col].astype("Int64")
    sin = res["poblacion"].isna()
    if sin.any():
        print(f"Aviso: {sin.sum()} municipios sin población en {anio}: {res.loc[sin, 'municipio'].tolist()[:10]}")
    columnas = ["ranking", "codigo_ine", "municipio", "anio", "poblacion", "hombres", "mujeres",
                "pct_espana", f"var_{anio_ini}_{anio}_pct"]
    return res[columnas].sort_values("ranking").reset_index(drop=True)


if __name__ == "__main__":
    resultado = calcular(limpiar(cargar_datos(RUTA_ENTRADA)), RUTA_MUNICIPIOS, ANIO)
    resultado.to_csv(RUTA_SALIDA, index=False, encoding="utf-8-sig")

    print(f"Año: {resultado['anio'].iloc[0]} | municipios: {len(resultado)} | "
          f"población total: {resultado['poblacion'].sum():,}".replace(",", "."))
    print(resultado.head(10).to_string(index=False))
    print(f"\nResultado guardado en {RUTA_SALIDA}")
