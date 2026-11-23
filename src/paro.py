"""Limpieza del paro registrado del SEPE: de los datos mensuales por municipio a una tabla
anual en data/processed/paro_municipios.csv (una fila por municipio de municipios.csv y año).

Origen: data/raw/socioeconomico/paro_municipios_sepe_mensual.csv (de paro_descarga.py) y
la población del padrón (data/raw/poblacion/ine_padron_poblacion_municipios_2016_2025.csv).

Secreto estadístico: el SEPE escribe "<5" cuando un municipio tiene entre 1 y 4 parados
(el 0 sí se publica). Esos meses se cuentan como VALOR_MENOS_5 = 2,5, el punto medio, para
no dejar sin dato a los municipios pequeños ni inflar su paro con solo los meses de 5 o más.

Uso: python src/paro.py   (o python run_pipeline.py --solo paro)
"""
import numpy as np
import pandas as pd

# ---------------- Configuración ----------------
RUTA_PARO = "data/raw/socioeconomico/paro_municipios_sepe_mensual.csv"
RUTA_POBLACION = "data/raw/poblacion/ine_padron_poblacion_municipios_2016_2025.csv"
RUTA_MUNICIPIOS = "data/processed/municipios.csv"     # lista maestra: codigo_ine, municipio

RUTA_SALIDA_MUNICIPIOS = "data/processed/paro_municipios.csv"

VALOR_MENOS_5 = 2.5              # valor que se da a los meses publicados como "<5"
ANIO_INICIO, ANIO_FIN = 2016, 2025


def cargar_datos():
    """Paro mensual (texto, con '<5'), padrón por municipio y año y lista maestra."""
    paro = pd.read_csv(RUTA_PARO, dtype={"cod_ine": str, "paro_registrado": str},
                       encoding="utf-8-sig")
    paro = paro.rename(columns={"cod_ine": "codigo_ine"})
    padron = pd.read_csv(RUTA_POBLACION, dtype={"codigo_ine": str}, encoding="utf-8-sig")
    municipios = pd.read_csv(RUTA_MUNICIPIOS, dtype={"codigo_ine": str}, encoding="utf-8-sig")
    for df in (paro, padron, municipios):
        df["codigo_ine"] = df["codigo_ine"].str.strip().str.zfill(5)
    return paro, padron[["codigo_ine", "anio", "poblacion"]], municipios[["codigo_ine", "municipio"]]


def limpiar_mensual(paro):
    """Pasa el paro a número: '<5' -> VALOR_MENOS_5 (marcado en 'menos_5'). Quita filas
    sin código o con valores que no se entienden, y los duplicados (municipio, año, mes)."""
    df = paro[paro["anio"].between(ANIO_INICIO, ANIO_FIN)].copy()
    df["menos_5"] = df["paro_registrado"].str.strip().eq("<5")
    df["paro"] = pd.to_numeric(df["paro_registrado"], errors="coerce")
    df.loc[df["menos_5"], "paro"] = VALOR_MENOS_5

    invalidos = df["paro"].isna() | (df["paro"] < 0) | ~df["codigo_ine"].str.fullmatch(r"\d{5}")
    if invalidos.any():
        print(f"Aviso: {invalidos.sum()} filas con código o paro no válidos (se descartan): "
              f"{df.loc[invalidos, 'paro_registrado'].unique()[:5]}")
    df = df[~invalidos]
    duplicados = df.duplicated(["codigo_ine", "anio", "mes"]).sum()
    if duplicados:
        print(f"Aviso: {duplicados} filas repetidas (municipio, año, mes): se quita la repetida")
        df = df.drop_duplicates(["codigo_ine", "anio", "mes"])
    print(f"Paro mensual: {len(df)} filas, {df['codigo_ine'].nunique()} municipios, "
          f"{df['menos_5'].mean() * 100:.1f} % de valores '<5'")
    return df


def anual_por_municipio(mensual):
    """Una fila por municipio y año: paro medio, el del último mes publicado y nº de meses.
    'paro_diciembre' es el último mes publicado del año: diciembre, salvo en 2020, cuyo CSV
    del SEPE acaba en noviembre."""
    ultimo_mes = mensual.groupby("anio")["mes"].transform("max")
    grupo = mensual.groupby(["codigo_ine", "anio"])
    anual = pd.DataFrame({
        "paro_medio_anual": grupo["paro"].mean().round(2),
        "paro_diciembre": mensual[mensual["mes"] == ultimo_mes].set_index(["codigo_ine", "anio"])["paro"],
        "meses": grupo["paro"].count(),
        "meses_menos_5": grupo["menos_5"].sum(),
    }).reset_index()
    meses_anio = mensual.groupby("anio")["mes"].nunique()
    incompletos = meses_anio[meses_anio < 12]
    if len(incompletos):
        print(f"Nota: años con menos de 12 meses publicados (media de los que hay): "
              f"{incompletos.to_dict()}")
    return anual


def tabla_municipios(anual, padron, municipios):
    """Rejilla completa municipio x año (los de la lista maestra): si un municipio no
    aparece en el SEPE un año, sus columnas quedan vacías (NaN, no 0)."""
    rejilla = pd.MultiIndex.from_product(
        [municipios["codigo_ine"], range(ANIO_INICIO, ANIO_FIN + 1)],
        names=["codigo_ine", "anio"]).to_frame(index=False)
    df = (rejilla.merge(municipios, on="codigo_ine", how="left")
                 .merge(anual, on=["codigo_ine", "anio"], how="left")
                 .merge(padron, on=["codigo_ine", "anio"], how="left"))
    for col in ["meses", "meses_menos_5", "poblacion"]:
        df[col] = df[col].astype("Int64")
    # Aproximada: parados entre TODA la población del padrón de ese año, no la activa
    df["tasa_paro_aprox"] = (df["paro_medio_anual"] / df["poblacion"] * 100).round(2)
    sobran = set(anual["codigo_ine"]) - set(municipios["codigo_ine"])
    if sobran:
        print(f"Nota: {len(sobran)} códigos del SEPE que no están en la lista maestra (municipios "
              f"fusionados o desaparecidos): no salen en la tabla, p. ej. {sorted(sobran)[:5]}")
    columnas = ["codigo_ine", "municipio", "anio", "paro_medio_anual", "paro_diciembre",
                "meses", "meses_menos_5", "poblacion", "tasa_paro_aprox"]
    return df[columnas].sort_values(["codigo_ine", "anio"]).reset_index(drop=True)


if __name__ == "__main__":
    paro_bruto, padron, municipios = cargar_datos()
    anual = anual_por_municipio(limpiar_mensual(paro_bruto))
    por_municipio = tabla_municipios(anual, padron, municipios)
    por_municipio.to_csv(RUTA_SALIDA_MUNICIPIOS, index=False, encoding="utf-8-sig")

    total = por_municipio.groupby("anio")["paro_medio_anual"].sum()
    print("\nParo registrado medio en España (suma de municipios):")
    print(total.map("{:,.0f}".format).to_string())
    print(f"\nGuardado: {RUTA_SALIDA_MUNICIPIOS} ({len(por_municipio)} filas, "
          f"{por_municipio['codigo_ine'].nunique()} municipios)")
