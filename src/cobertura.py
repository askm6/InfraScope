import re

import pandas as pd

# ---------------- Configuración ----------------
RUTA_ENTRADA = "data/raw/telecomunicaciones/cobertura_banda_ancha_municipios.csv"
RUTA_MUNICIPIOS = "data/processed/municipios.csv"     # lista maestra: nombre único por código
RUTA_SALIDA_ANUAL = "data/processed/cobertura_anual.csv"
RUTA_SALIDA_MUNICIPIOS = "data/processed/cobertura_municipios.csv"

NUM_MUNICIPIOS = 29
SOLO_ULTIMO_ANIO = True  # solo el último año de los datos (junio más reciente)
TOLERANCIA = 1e-6        # valores como 1.0000000007 son redondeo de la fuente -> 1

# Nombres de la fuente (sin el "(junio AAAA)") -> nombres cortos
TECNOLOGIAS = {
    "Inalámbrico fijo": "inalambrico_fijo",
    "FTTH": "ftth",
    "HFC": "hfc",
    "Cob. 30Mbps condiciones máxima demanda": "cob_30mbps",
    "Cob. 100Mbps condiciones máxima demanda": "cob_100mbps",
    "Cob. 1Gbps descarga condiciones máxima demanda": "cob_1gbps",
    "4G": "cob_4g",
    "5G": "cob_5g",
    "5G-Banda 3,5GHz": "cob_5g_3_5ghz",
}

# Tecnologías de las que se calcula la variación (puntos porcentuales) entre el primer y el último año
TECNOLOGIAS_VARIACION = ["ftth", "cob_1gbps", "cob_5g"]

# Pesos del índice de conectividad (deben sumar 1)
PESOS_CONECTIVIDAD = {
    "cob_1gbps": 0.4,
    "ftth": 0.3,
    "cob_5g": 0.2,
    "cob_5g_3_5ghz": 0.1,
}

PATRON_COLUMNA = re.compile(r"^(?P<tecnologia>.+) \(junio (?P<anio>\d{4})\)$")


def cargar_datos(ruta):
    """Lee el informe de cobertura con el código del municipio (CMUN) como texto."""
    df = pd.read_csv(ruta, dtype={"CMUN": str}, encoding="utf-8")
    df = df.rename(columns={"CMUN": "codigo_ine", "Municipio": "municipio",
                            "Provincia": "provincia", "Comunidad Autónoma": "ccaa",
                            "Habitantes": "habitantes", "Hogares": "hogares"})
    df["codigo_ine"] = df["codigo_ine"].astype(str).str.strip().str.zfill(5)
    return df


def a_formato_largo(df):
    """Una fila por municipio, año y tecnología a partir de las columnas '<tecnología> (junio <año>)'."""
    columnas = {}
    for col in df.columns:
        encontrado = PATRON_COLUMNA.match(col)
        if encontrado:
            columnas[col] = (encontrado["tecnologia"].strip(), int(encontrado["anio"]))

    desconocidas = {tec for tec, _ in columnas.values()} - set(TECNOLOGIAS)
    if desconocidas:
        print(f"Aviso: tecnologías no previstas (se ignoran): {sorted(desconocidas)}")

    largo = df.melt(id_vars=["codigo_ine"], value_vars=list(columnas),
                    var_name="columna", value_name="cobertura")
    largo["tecnologia"] = largo["columna"].map(lambda c: columnas[c][0]).map(TECNOLOGIAS)
    largo["anio"] = largo["columna"].map(lambda c: columnas[c][1])
    largo = largo.dropna(subset=["tecnologia"])
    return largo[["codigo_ine", "anio", "tecnologia", "cobertura"]]


def limpiar(largo):
    """Comprueba nulos, rango 0-1 y nº de municipios; pasa la cobertura a % con 1 decimal."""
    largo = largo.drop_duplicates(subset=["codigo_ine", "anio", "tecnologia"]).copy()
    largo["cobertura"] = pd.to_numeric(largo["cobertura"], errors="coerce")

    nulos = largo[largo["cobertura"].isna()]
    if len(nulos):
        print(f"Aviso: {len(nulos)} valores nulos de cobertura "
              f"(tecnologías: {sorted(nulos['tecnologia'].unique())})")

    fuera = largo[(largo["cobertura"] < -TOLERANCIA) | (largo["cobertura"] > 1 + TOLERANCIA)]
    if len(fuera):
        print(f"Aviso: {len(fuera)} valores fuera del rango 0-1 (se recortan):")
        print(fuera.to_string(index=False))
    largo["cobertura"] = largo["cobertura"].clip(0, 1)

    num = largo["codigo_ine"].nunique()
    if num != NUM_MUNICIPIOS:
        print(f"Aviso: hay {num} municipios en vez de {NUM_MUNICIPIOS}")

    largo["cobertura_pct"] = (largo["cobertura"] * 100).round(1)
    return largo.drop(columns="cobertura")


def nombres_municipios(df):
    """Nombre único por código: el de la lista maestra y, si falta, el de la fuente."""
    try:
        maestra = pd.read_csv(RUTA_MUNICIPIOS, dtype={"codigo_ine": str}, encoding="utf-8")
        maestra["codigo_ine"] = maestra["codigo_ine"].str.zfill(5)
        nombres = maestra.set_index("codigo_ine")["municipio"]
    except FileNotFoundError:
        print(f"Aviso: no se encuentra {RUTA_MUNICIPIOS}, se usan los nombres de la fuente")
        nombres = pd.Series(dtype=str)

    faltan = set(df["codigo_ine"]) - set(nombres.index)
    if faltan and len(nombres):
        print(f"Aviso: códigos que no están en {RUTA_MUNICIPIOS}: {sorted(faltan)}")
    info = df[["codigo_ine", "municipio", "provincia", "habitantes", "hogares"]].copy()
    info["municipio"] = info["codigo_ine"].map(nombres).fillna(info["municipio"])
    return info


def calcular(largo, info):
    """Una fila por municipio: cobertura del último año, variaciones e índice de conectividad."""
    anio_ini, anio_fin = largo["anio"].min(), largo["anio"].max()
    ancho = largo.pivot(index=["codigo_ine", "anio"], columns="tecnologia",
                        values="cobertura_pct").reset_index()
    ancho.columns.name = None

    ultimo = ancho[ancho["anio"] == anio_fin].drop(columns="anio")
    primero = ancho[ancho["anio"] == anio_ini].set_index("codigo_ine")
    df = info.merge(ultimo, on="codigo_ine", how="left")
    df.insert(df.columns.get_loc("hogares") + 1, "anio", anio_fin)

    # Variación en puntos porcentuales (no en %): 80 % -> 95 % son +15 pp
    for tec in TECNOLOGIAS_VARIACION:
        df[f"var_{tec}_pp"] = (df[tec] - df["codigo_ine"].map(primero[tec])).round(1)

    # Media ponderada de coberturas (0-100) pasada a 0-1
    df["indice_conectividad"] = sum(peso * df[tec] / 100
                                    for tec, peso in PESOS_CONECTIVIDAD.items()).round(3)

    columnas = (["codigo_ine", "municipio", "provincia", "habitantes", "hogares", "anio"]
                + list(TECNOLOGIAS.values())
                + [f"var_{tec}_pp" for tec in TECNOLOGIAS_VARIACION]
                + ["indice_conectividad"])
    return df[columnas].sort_values("indice_conectividad", ascending=False).reset_index(drop=True)


if __name__ == "__main__":
    assert abs(sum(PESOS_CONECTIVIDAD.values()) - 1) < 1e-9, "Los pesos de conectividad deben sumar 1"

    bruto = cargar_datos(RUTA_ENTRADA)
    info = nombres_municipios(bruto)
    largo = limpiar(a_formato_largo(bruto))
    if SOLO_ULTIMO_ANIO:
        largo = largo[largo["anio"] == largo["anio"].max()].reset_index(drop=True)
    resultado = calcular(largo, info)

    anual = (largo.merge(info[["codigo_ine", "municipio"]], on="codigo_ine", how="left")
                  [["codigo_ine", "municipio", "anio", "tecnologia", "cobertura_pct"]]
                  .sort_values(["codigo_ine", "tecnologia", "anio"]).reset_index(drop=True))

    anual.to_csv(RUTA_SALIDA_ANUAL, index=False, encoding="utf-8-sig")
    resultado.to_csv(RUTA_SALIDA_MUNICIPIOS, index=False, encoding="utf-8-sig")

    anio_ini, anio_fin = largo["anio"].min(), largo["anio"].max()
    print(f"Municipios: {len(resultado)} | años {anio_ini}-{anio_fin} | "
          f"tecnologías: {largo['tecnologia'].nunique()} | filas anuales: {len(anual)}")
    print("Pesos del índice: " + ", ".join(f"{t} {p:.0%}" for t, p in PESOS_CONECTIVIDAD.items()))

    columnas = ["municipio"] + list(PESOS_CONECTIVIDAD) + ["indice_conectividad"]
    print(f"\n5 municipios con MEJOR conectividad ({anio_fin}):")
    print(resultado.head(5)[columnas].to_string(index=False))
    print(f"\n5 municipios con PEOR conectividad ({anio_fin}):")
    print(resultado.tail(5)[columnas].to_string(index=False))
    print(f"\nResultado guardado en {RUTA_SALIDA_ANUAL} y {RUTA_SALIDA_MUNICIPIOS}")
