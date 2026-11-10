import pandas as pd

# ---------------- Configuración ----------------
RUTA_ENTRADA = "data/raw/agua/embalses_semanal_2016_2026.csv"
RUTA_SALIDA_EMBALSES = "data/processed/embalses_semanal_limpio.csv"
RUTA_SALIDA_CUENCAS = "data/processed/cuencas_semanal.csv"
MINIMO_CAPACIDAD_HM3 = 100          # embalses "grandes" (hm³ = 1.000 millones de litros)
ANIO_DESDE = None                   # p.ej. 2020 para quedarse solo con los últimos años


def cargar_datos(ruta):
    """Lee el CSV semanal de embalses (MITECO) y pone nombres de columnas cómodos."""
    df = pd.read_csv(ruta, encoding="utf-8")
    df = df.rename(columns={
        "ambito_nombre": "cuenca",
        "embalse_nombre": "embalse",
        "agua_total": "capacidad_hm3",
        "agua_actual": "reserva_hm3",
        "electrico_flag": "uso_electrico",
    })
    df["fecha"] = pd.to_datetime(df["fecha"], errors="coerce")
    for col in ["capacidad_hm3", "reserva_hm3", "uso_electrico"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def limpiar(df, anio_desde=None):
    """Quita filas inválidas, duplicados y corrige reservas imposibles."""
    df = df.dropna(subset=["fecha", "embalse", "capacidad_hm3", "reserva_hm3"]).copy()
    df["cuenca"] = df["cuenca"].str.strip()
    df["embalse"] = df["embalse"].str.strip()

    if anio_desde:
        df = df[df["fecha"].dt.year >= anio_desde]

    # Valores imposibles: capacidad <= 0 o reserva negativa
    df = df[(df["capacidad_hm3"] > 0) & (df["reserva_hm3"] >= 0)]

    # Un embalse no puede tener más agua que su capacidad -> se recorta al máximo
    df["reserva_hm3"] = df["reserva_hm3"].clip(upper=df["capacidad_hm3"])

    # Un único dato por embalse y semana
    df = df.drop_duplicates(subset=["embalse", "cuenca", "fecha"])

    df["uso_electrico"] = df["uso_electrico"].map({1: "sí", 0: "no"}).fillna("no")
    return df.sort_values(["cuenca", "embalse", "fecha"]).reset_index(drop=True)


def calcular(df):
    """Añade año, semana ISO y % de llenado de cada embalse."""
    iso = df["fecha"].dt.isocalendar()
    df["anio"] = iso["year"].astype(int)
    df["semana"] = iso["week"].astype(int)
    df["llenado_pct"] = (df["reserva_hm3"] / df["capacidad_hm3"] * 100).round(1)
    return df[["fecha", "anio", "semana", "cuenca", "embalse", "uso_electrico",
               "capacidad_hm3", "reserva_hm3", "llenado_pct"]]


def resumen_cuencas(df):
    """Suma por cuenca y semana: capacidad total, reserva total y % de llenado."""
    cuencas = (df.groupby(["fecha", "anio", "semana", "cuenca"], as_index=False)
                 .agg(num_embalses=("embalse", "nunique"),
                      capacidad_hm3=("capacidad_hm3", "sum"),
                      reserva_hm3=("reserva_hm3", "sum")))
    cuencas["llenado_pct"] = (cuencas["reserva_hm3"] / cuencas["capacidad_hm3"] * 100).round(1)
    return cuencas.sort_values(["cuenca", "fecha"]).reset_index(drop=True)


if __name__ == "__main__":
    bruto = cargar_datos(RUTA_ENTRADA)
    resultado = calcular(limpiar(bruto, ANIO_DESDE))
    seleccion = resultado[resultado["capacidad_hm3"] >= MINIMO_CAPACIDAD_HM3]
    cuencas = resumen_cuencas(resultado)          # las cuencas con TODOS los embalses

    seleccion.to_csv(RUTA_SALIDA_EMBALSES, index=False, encoding="utf-8-sig")
    cuencas.to_csv(RUTA_SALIDA_CUENCAS, index=False, encoding="utf-8-sig")

    ultima = resultado["fecha"].max()
    print(f"Periodo: {resultado['fecha'].min():%Y-%m-%d} -> {ultima:%Y-%m-%d}")
    print(f"Filas leídas: {len(bruto)} | tras limpiar: {len(resultado)}")
    print(f"Embalses analizados: {resultado['embalse'].nunique()}")
    print(f"Con al menos {MINIMO_CAPACIDAD_HM3} hm³: {seleccion['embalse'].nunique()}")
    print(f"\nLlenado por cuenca en la última semana ({ultima:%Y-%m-%d}):")
    print(cuencas[cuencas["fecha"] == ultima]
          .sort_values("llenado_pct")[["cuenca", "num_embalses", "capacidad_hm3",
                                       "reserva_hm3", "llenado_pct"]]
          .to_string(index=False))
    print(f"\nResultado guardado en {RUTA_SALIDA_EMBALSES} y {RUTA_SALIDA_CUENCAS}")
