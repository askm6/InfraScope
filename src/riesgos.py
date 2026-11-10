import numpy as np
import pandas as pd

# ---------------- Configuración ----------------
CARPETA_ENTRADA = "data/raw/riesgos/"
RUTA_SISMICO = CARPETA_ENTRADA + "riesgo_sismico_ncse02.csv"
RUTA_ARPSI = CARPETA_ENTRADA + "inundaciones_arpsi_municipios.csv"
RUTA_EVENTOS = CARPETA_ENTRADA + "inundaciones_eventos_municipios_2016_2025.csv"
RUTA_SALIDA = "data/processed/riesgos_municipios.csv"

ANIO_DESDE, ANIO_HASTA = 2016, 2025

# Municipios fuera del anejo de la NCSE-02: aceleración < 0,04 g -> se asume 0,03 g
ACELERACION_POR_DEFECTO = 0.03
UMBRAL_SISMICO_MEDIO = 0.04         # g (desde aquí, nivel medio)
UMBRAL_SISMICO_ALTO = 0.08          # g (por encima, nivel alto)

# Pesos de los índices (cada grupo debe sumar 1)
PESO_SISMICO = 0.5
PESO_INUNDACION = 0.5
PESO_ARPSI = 0.5                    # dentro del índice de inundación
PESO_EVENTOS = 0.5                  # dentro del índice de inundación

# Los códigos REE/MITECO del nivel de daño se agrupan en categorías legibles
NIVELES_DANIO = {
    "L": "Bajo", "L-Bajo": "Bajo",
    "M": "Medio", "M-Medio": "Medio",
    "H": "Alto", "H-Alto": "Alto",
    "VH-Muy Alto": "Muy alto",
    "I-Insignificante": "Insignificante",
    "U-Desconocido": "Desconocido",
}
NIVELES_GRAVES = ["Alto", "Muy alto"]

OBSERVACION_ACA = ("0 ARPSI: sus cuencas las gestiona la Agència Catalana de l'Aigua "
                   "y no están en el catálogo estatal")
OBSERVACIONES = {
    "08019": OBSERVACION_ACA,       # Barcelona
    "08101": OBSERVACION_ACA,       # L'Hospitalet de Llobregat
    "08015": OBSERVACION_ACA,       # Badalona
}


def codigo_ine(serie):
    """Deja el código INE como texto de 5 dígitos (recupera los ceros iniciales)."""
    return serie.astype(str).str.strip().str.zfill(5)


def cargar_datos():
    """Lee los tres CSV de riesgos con los códigos INE como texto."""
    sismico = pd.read_csv(RUTA_SISMICO, dtype={"cod_ine": str}, encoding="utf-8")
    sismico = sismico.rename(columns={"cod_ine": "codigo_ine"})
    arpsi = pd.read_csv(RUTA_ARPSI, dtype={"codigo_ine": str}, encoding="utf-8")
    eventos = pd.read_csv(RUTA_EVENTOS, dtype={"codigo_ine": str}, encoding="utf-8")
    for df in (sismico, arpsi, eventos):
        df["codigo_ine"] = codigo_ine(df["codigo_ine"])
    return sismico, arpsi, eventos


def limpiar_sismico(df):
    """Rellena la aceleración de los municipios fuera de la norma y asigna un nivel."""
    df = df.drop_duplicates(subset=["codigo_ine"]).copy()
    df["municipio"] = df["municipio"].str.strip()
    df["aceleracion_g"] = (pd.to_numeric(df["aceleracion_sismica_basica_g"], errors="coerce")
                             .fillna(ACELERACION_POR_DEFECTO))
    df["nivel_sismico"] = np.select(
        [df["aceleracion_g"] < UMBRAL_SISMICO_MEDIO,
         df["aceleracion_g"] <= UMBRAL_SISMICO_ALTO],
        ["Bajo", "Medio"], default="Alto")
    return df[["codigo_ine", "municipio", "aceleracion_g", "nivel_sismico"]]


def limpiar_arpsi(df):
    """Nº de zonas oficiales de riesgo de inundación (ARPSI) por municipio."""
    df = df.drop_duplicates(subset=["codigo_ine"]).copy()
    df["num_arpsi"] = pd.to_numeric(df["num_arpsi"], errors="coerce").fillna(0).astype(int)
    return df[["codigo_ine", "num_arpsi"]]


def limpiar_eventos(df):
    """Unifica el nivel de daño y se queda con los eventos del periodo, sin repetir."""
    df = df.copy()
    df["nivel_danio"] = df["nivel_danio_economico"].str.strip().map(NIVELES_DANIO)
    sin_traducir = df.loc[df["nivel_danio"].isna(), "nivel_danio_economico"].unique()
    if len(sin_traducir):
        print(f"Aviso: niveles de daño desconocidos: {list(sin_traducir)}")
    df["nivel_danio"] = df["nivel_danio"].fillna("Desconocido")

    df["anio"] = pd.to_numeric(df["anio"], errors="coerce")
    df = df[df["anio"].between(ANIO_DESDE, ANIO_HASTA)]
    for col in ["victimas", "evacuados"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).clip(lower=0)
    return df.drop_duplicates(subset=["codigo_ine", "cod_evento"])


def resumen_eventos(df):
    """Por municipio: nº de eventos, nº con daño alto o muy alto, víctimas y evacuados."""
    df = df.assign(evento_grave=df["nivel_danio"].isin(NIVELES_GRAVES))
    return (df.groupby("codigo_ine", as_index=False)
              .agg(num_eventos=("cod_evento", "nunique"),
                   num_eventos_graves=("evento_grave", "sum"),
                   victimas=("victimas", "sum"),
                   evacuados=("evacuados", "sum")))


def normalizar(serie):
    """Escala de 0 a 1 dividiendo entre el máximo (0 = sin riesgo, 1 = el más expuesto)."""
    maximo = serie.max()
    return serie / maximo if maximo > 0 else serie * 0.0


def calcular(sismico, arpsi, eventos):
    """Une todo en una fila por municipio y calcula los índices de riesgo."""
    df = (sismico.merge(arpsi, on="codigo_ine", how="left")
                 .merge(resumen_eventos(eventos), on="codigo_ine", how="left"))

    # Municipios sin eventos o sin ARPSI -> 0
    columnas_conteo = ["num_arpsi", "num_eventos", "num_eventos_graves", "victimas", "evacuados"]
    df[columnas_conteo] = df[columnas_conteo].fillna(0).astype(int)

    df["indice_sismico"] = normalizar(df["aceleracion_g"])
    # Media ponderada de valores 0-1 -> también queda entre 0 y 1
    df["indice_inundacion"] = (PESO_ARPSI * normalizar(df["num_arpsi"])
                               + PESO_EVENTOS * normalizar(df["num_eventos"]))
    df["indice_riesgo"] = (PESO_SISMICO * df["indice_sismico"]
                           + PESO_INUNDACION * df["indice_inundacion"])
    for col in ["indice_sismico", "indice_inundacion", "indice_riesgo"]:
        df[col] = df[col].round(3)

    df["observaciones"] = df["codigo_ine"].map(OBSERVACIONES).fillna("")
    return df.sort_values("indice_riesgo", ascending=False).reset_index(drop=True)


if __name__ == "__main__":
    assert abs(PESO_SISMICO + PESO_INUNDACION - 1) < 1e-9, "Los pesos sísmico + inundación deben sumar 1"
    assert abs(PESO_ARPSI + PESO_EVENTOS - 1) < 1e-9, "Los pesos ARPSI + eventos deben sumar 1"

    sismico_bruto, arpsi_bruto, eventos_bruto = cargar_datos()
    resultado = calcular(limpiar_sismico(sismico_bruto),
                         limpiar_arpsi(arpsi_bruto),
                         limpiar_eventos(eventos_bruto))
    resultado.to_csv(RUTA_SALIDA, index=False, encoding="utf-8-sig")

    columnas = ["municipio", "aceleracion_g", "nivel_sismico", "num_arpsi",
                "num_eventos", "indice_sismico", "indice_inundacion", "indice_riesgo"]
    print(f"Municipios: {len(resultado)} | eventos de inundación {ANIO_DESDE}-{ANIO_HASTA}: "
          f"{resultado['num_eventos'].sum()}")
    print(f"Pesos: sísmico {PESO_SISMICO:.0%} / inundación {PESO_INUNDACION:.0%} "
          f"(ARPSI {PESO_ARPSI:.0%}, eventos {PESO_EVENTOS:.0%})")
    print("\n5 municipios con MÁS riesgo:")
    print(resultado.head(5)[columnas].to_string(index=False))
    print("\n5 municipios con MENOS riesgo:")
    print(resultado.tail(5)[columnas].to_string(index=False))
    print(f"\nResultado guardado en {RUTA_SALIDA}")
