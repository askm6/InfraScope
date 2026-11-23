"""Porcentaje de personas ocupadas que trabajan fuera de su municipio de residencia.

Fuente: Matriz de municipio de residencia por municipio de trabajo del Censo Anual,
último año disponible en INE (2023). El porcentaje usa como denominador las personas
ocupadas residentes en cada municipio, no toda la población municipal.
"""
from pathlib import Path
import re

import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent
RUTA_MATRIZ = RAIZ / "data" / "raw" / "trabajo" / "matriz_residencia_trabajo_2023.xlsb"
RUTA_SALIDA = RAIZ / "data" / "processed" / "movilidad_laboral_municipios.csv"


def codigo_ine(valor):
    encontrado = re.search(r"(?<!\d)(\d{5})(?!\d)", str(valor))
    return encontrado.group(1) if encontrado else None


def procesar_matriz(df):
    """Procesa las filas de la matriz INE, que está publicada en formato largo."""
    datos = df.iloc[2:].copy()
    datos = datos.iloc[:, :9]
    datos.columns = ["prov_res", "nombre_prov_res", "mun_res", "nombre_mun_res",
                     "prov_trab", "nombre_prov_trab", "mun_trab", "nombre_mun_trab", "ocupados"]
    datos["codigo_ine"] = (datos["prov_res"].astype(str).str.extract(r"(\d{2})", expand=False)
                           + datos["mun_res"].astype(str).str.extract(r"(\d{3})", expand=False))
    destino = (datos["prov_trab"].astype(str).str.extract(r"(\d{2})", expand=False)
               + datos["mun_trab"].astype(str).str.extract(r"(\d{3})", expand=False))
    datos["ocupados"] = pd.to_numeric(datos["ocupados"], errors="coerce").fillna(0)
    datos = datos[datos["codigo_ine"].notna()]
    datos["fuera"] = destino.notna() & destino.ne(datos["codigo_ine"])
    res = (datos.groupby("codigo_ine", as_index=False)
           .agg(ocupados_residentes=("ocupados", "sum"),
                ocupados_trabajan_fuera=("ocupados", lambda s: s[datos.loc[s.index, "fuera"]].sum())))
    res["porcentaje_trabaja_fuera_municipio"] = (
        res["ocupados_trabajan_fuera"] / res["ocupados_residentes"] * 100).round(2)
    res["anio"] = 2023
    return res


def main():
    if not RUTA_MATRIZ.exists():
        raise FileNotFoundError(
            f"Falta {RUTA_MATRIZ.relative_to(RAIZ)}. Descarga la matriz de municipio de "
            "residencia por municipio de trabajo desde INEbase (Censo anual de población, "
            "Ocupación y actividad 2021-2023)."
        )
    matriz = pd.read_excel(RUTA_MATRIZ, sheet_name="C23", header=None, engine="pyxlsb")
    res = procesar_matriz(matriz)
    ruta_maestra = RAIZ / "data" / "processed" / "municipios.csv"
    if ruta_maestra.exists():
        nombres = pd.read_csv(ruta_maestra, dtype={"codigo_ine": str}, encoding="utf-8-sig")
        res = nombres[["codigo_ine", "municipio"]].merge(res, on="codigo_ine", how="left")
    RUTA_SALIDA.parent.mkdir(parents=True, exist_ok=True)
    res.to_csv(RUTA_SALIDA, index=False, encoding="utf-8-sig")
    print(f"Guardado {RUTA_SALIDA.relative_to(RAIZ)}: {len(res):,} municipios, año 2023")


if __name__ == "__main__":
    main()
