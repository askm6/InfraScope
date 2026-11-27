"""Pasa a Parquet los CSV limpios de data/processed/: capas Silver y Gold del Data Lake.

Por qué Parquet: guarda los datos por columnas, comprimidos y con el tipo de cada columna.
Ocupa menos, se lee más rápido (se pueden cargar solo las columnas que hacen falta) y no
hay que volver a adivinar los tipos al leer (en CSV, el código INE 01001 se leía como 1001).

Qué se hace con cada CSV de data/processed/:
  1. Tipar: código INE como texto de 5 cifras, años, meses y contadores como números
     enteros (aunque tengan huecos) y fechas como fecha.
  2. Validar: que la clave de la tabla no tenga duplicados ni huecos y que los códigos estén
     bien escritos (y avisar si algún código INE no está en la lista maestra municipios.csv).
  3. Guardar en data/silver/<nombre>.parquet, o en data/gold/ si es una tabla final, y
     apuntar en el catalogo.json de la capa: origen, filas, columnas, tipos, % de nulos,
     tamaño y huella (sha256) del CSV.
  4. Carga incremental: si un CSV no ha cambiado desde la última vez (misma huella y mismas
     reglas de tipado), no se vuelve a convertir.

Uso (desde la raíz del proyecto):
    python src/convertir_parquet.py                    # convierte solo lo que ha cambiado
    python src/convertir_parquet.py --forzar           # vuelve a convertir todo
    python src/convertir_parquet.py --solo energia_municipios paro_municipios
    python run_pipeline.py --solo convertir_parquet    # lo mismo desde el pipeline
"""
import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa

try:                                    # python -m src.convertir_parquet / tests
    from src.lago import MARCA_DESACTUALIZADO, Capa, carpeta_trabajo, ruta
except ModuleNotFoundError as error:    # python src/convertir_parquet.py
    if error.name != "src":
        raise
    from lago import MARCA_DESACTUALIZADO, Capa, carpeta_trabajo, ruta

# ---------------- Configuración ----------------
# Súbelo cuando cambien las reglas de tipado o validación: obliga a reconvertir todo
VERSION_ESQUEMA = 1

# Tablas finales, listas para el dashboard y los modelos: van a Gold (el resto, a Silver)
DATASETS_GOLD = {"tabla_integrada"}          # tabla única por municipio (issue #34)

ANCHO_CODIGO = {"codigo_ine": 5, "codigo_provincia": 2}   # se guardan como texto con ceros
PATRON_CODIGO = re.compile(r"^(cod|codigo)_|_ine$")       # otros códigos: se avisa si son números

# Columnas que deben ser números enteros (años, meses, contadores y personas)
PATRON_ENTERO = re.compile(
    r"^(anio|mes|semana|meses|ranking|poblacion|habitantes|hogares|hombres|mujeres"
    r"|victimas|evacuados)(_|$)|^(n|num)_")
PATRON_FECHA = re.compile(r"^fecha(_|$)")
FECHA_COMPLETA = r"\d{4}-\d{2}-\d{2}([ T].*)?"           # AAAA-MM-DD, con hora opcional
MAYOR_ENTERO_EXACTO = 2 ** 53                              # a partir de aquí un float pierde precisión

# Columnas que identifican cada fila (comprobado sobre los datos reales). Las tablas
# *_municipios que no aparecen aquí tienen una fila por municipio: clave codigo_ine
CLAVES = {
    "municipios": ["codigo_ine"],
    "paro_municipios": ["codigo_ine", "anio"],
    "socioeconomico_anual": ["codigo_ine", "anio"],
    "consumo_electrico_mensual": ["codigo_ine", "anio", "mes"],
    "clima": ["codigo_ine"],
    "clima_extremos": ["codigo_ine", "anio", "variable"],
    "cobertura_anual": ["codigo_ine", "anio", "tecnologia"],
    "cuencas_semanal": ["fecha", "cuenca"],
    "embalses_semanal_limpio": ["fecha", "embalse"],
    "cuencas_picos_llenado": ["cuenca", "anio", "tipo"],
    "espacios_protegidos_limpio": ["codigo_ine", "sitecode"],
    "aeropuertos": ["codigo_icao"],
    "cpd_existentes": ["id_cpd"],
}

LISTA_MAESTRA = "municipios"
COMPRESION = "zstd"                      # buena compresión y lectura rápida

# Estado de cada dataset al terminar
CONVERTIDO, SIN_CAMBIOS, ERROR = "convertido", "sin cambios", "error"

# Errores de un dataset que no deben parar la conversión de los demás
# (archivo abierto en otro programa, CSV mal formado, tipo que Parquet no admite...)
ERRORES_DATASET = (OSError, ValueError, TypeError, pa.ArrowException)


# ---------------- Tipos ----------------

def normalizar_codigo(serie: pd.Series, ancho: int) -> pd.Series:
    """1001 / 1001.0 / '01001' -> '01001' (texto con `ancho` cifras). Los huecos se mantienen."""
    texto = serie.astype("string").str.strip().str.replace(r"\.0$", "", regex=True)
    return texto.str.zfill(ancho)


def a_fecha(serie: pd.Series) -> pd.Series:
    """Texto 'AAAA-MM-DD' -> fecha. Si algún valor no es una fecha completa (p. ej. '2016-03'
    o un número), la columna se deja como estaba para no inventar el día."""
    if pd.api.types.is_numeric_dtype(serie):
        return serie
    valores = serie.dropna().astype(str)
    if valores.empty or not valores.str.fullmatch(FECHA_COMPLETA).all():
        return serie
    fechas = pd.to_datetime(serie, errors="coerce", format="ISO8601")
    if fechas.isna().sum() > serie.isna().sum():
        return serie
    return fechas


def a_entero(serie: pd.Series) -> pd.Series:
    """Número sin decimales -> entero con huecos (Int64). Si hay decimales o valores que no
    caben exactos en un entero (infinito, más de 2^53), no se toca."""
    if not pd.api.types.is_numeric_dtype(serie) or pd.api.types.is_bool_dtype(serie):
        return serie
    valores = serie.dropna().to_numpy(dtype="float64")
    if not np.isfinite(valores).all() or (np.abs(valores) >= MAYOR_ENTERO_EXACTO).any():
        return serie
    if not (valores == np.round(valores)).all():
        return serie
    return serie.astype("Int64")


def tipar(df: pd.DataFrame) -> pd.DataFrame:
    """Devuelve una copia de `df` con el tipo correcto en cada columna (no cambia `df`)."""
    resultado = df.copy()
    for columna in resultado.columns:
        if columna in ANCHO_CODIGO:
            resultado[columna] = normalizar_codigo(resultado[columna], ANCHO_CODIGO[columna])
        elif PATRON_FECHA.match(columna):
            resultado[columna] = a_fecha(resultado[columna])
        elif PATRON_ENTERO.match(columna):
            resultado[columna] = a_entero(resultado[columna])
    return resultado


# ---------------- Validación ----------------

def clave(nombre: str, df: pd.DataFrame) -> list[str] | None:
    """Columnas que identifican cada fila del dataset (None si no tiene clave conocida)."""
    if nombre in CLAVES:
        return CLAVES[nombre]
    if nombre.endswith("_municipios") and "codigo_ine" in df.columns:
        return ["codigo_ine"]
    return None


def errores_de_clave(df: pd.DataFrame, columnas_clave: list[str]) -> list[str]:
    """La clave tiene que existir, no tener huecos y no repetirse."""
    faltan = [c for c in columnas_clave if c not in df.columns]
    if faltan:
        return [f"faltan las columnas de la clave: {faltan}"]
    errores = []
    vacias = int(df[columnas_clave].isna().any(axis=1).sum())
    if vacias:
        errores.append(f"{vacias} filas con la clave {columnas_clave} vacía")
    repetidas = int(df.dropna(subset=columnas_clave).duplicated(columnas_clave).sum())
    if repetidas:
        errores.append(f"{repetidas} filas duplicadas en la clave {columnas_clave}")
    return errores


def errores_de_codigos(df: pd.DataFrame) -> list[str]:
    """codigo_ine tiene que tener 5 cifras y codigo_provincia 2."""
    errores = []
    for columna, ancho in ANCHO_CODIGO.items():
        if columna not in df.columns:
            continue
        codigos = df[columna].dropna().astype(str)
        mal = codigos[~codigos.str.fullmatch(rf"\d{{{ancho}}}")]
        if len(mal):
            errores.append(f"{columna} mal formado en {len(mal)} filas, p. ej. {mal.iloc[0]!r}")
    return errores


def avisos_de_tipos(df: pd.DataFrame) -> list[str]:
    """Columnas que probablemente tienen un tipo distinto del esperado (no bloquean)."""
    avisos = []
    for columna in df.columns:
        es_numero = (pd.api.types.is_numeric_dtype(df[columna])
                     and not pd.api.types.is_bool_dtype(df[columna]))
        if columna not in ANCHO_CODIGO and PATRON_CODIGO.search(columna) and es_numero:
            avisos.append(f"'{columna}' parece un código pero es un número: puede perder "
                          "ceros a la izquierda (añádelo a ANCHO_CODIGO)")
        elif PATRON_ENTERO.match(columna) and df[columna].dtype == "float64":
            avisos.append(f"'{columna}' debería ser un número entero pero tiene decimales o "
                          "valores fuera de rango: se guarda como decimal")
    return avisos


def validar(nombre: str, df: pd.DataFrame, codigos_validos: set | None) -> tuple[list, list]:
    """Devuelve (errores, avisos). Con algún error, el dataset no se guarda."""
    columnas_clave = clave(nombre, df)
    errores = errores_de_clave(df, columnas_clave) if columnas_clave else []
    errores += errores_de_codigos(df)
    avisos = avisos_de_tipos(df)
    if "codigo_ine" in df.columns and codigos_validos is not None and not errores:
        desconocidos = sorted(set(df["codigo_ine"].dropna()) - codigos_validos)
        if desconocidos:
            avisos.append(f"{len(desconocidos)} códigos no están en municipios.csv, "
                          f"p. ej. {desconocidos[:5]}")
    return errores, avisos


# ---------------- Lectura, escritura y catálogo ----------------

def huella(archivo: Path) -> str:
    """sha256 del archivo: si no cambia, el CSV es el mismo que la última vez."""
    h = hashlib.sha256()
    with open(archivo, "rb") as f:
        for bloque in iter(lambda: f.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def leer_csv(archivo: Path) -> pd.DataFrame:
    """Lee un CSV limpio. Los códigos se leen como texto para no perder los ceros."""
    cabecera = pd.read_csv(archivo, nrows=0, encoding="utf-8-sig").columns
    como_texto = {c: "string" for c in cabecera if c in ANCHO_CODIGO}
    return pd.read_csv(archivo, dtype=como_texto, encoding="utf-8-sig", low_memory=False)


def escribir_seguro(destino: Path, escribir) -> None:
    """Escribe en un temporal y lo renombra: nunca queda un archivo a medias. Si falla,
    se borra el temporal y el error sigue hacia arriba."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporal = destino.with_name(destino.name + ".tmp")
    try:
        escribir(temporal)
        temporal.replace(destino)
    except BaseException:
        temporal.unlink(missing_ok=True)
        raise


def guardar_parquet(df: pd.DataFrame, destino: Path) -> None:
    escribir_seguro(destino, lambda t: df.to_parquet(t, index=False, compression=COMPRESION))


def describir(nombre: str, df: pd.DataFrame, csv: Path, destino: Path, capa: Capa, sha: str) -> dict:
    """Entrada del catálogo de la capa para un dataset."""
    nulos = (df.isna().mean() * 100).round(1)
    return {
        "capa": capa.name.lower(),
        "origen": f"data/processed/{csv.name}",
        "sha256": sha,
        "version_esquema": VERSION_ESQUEMA,
        "filas": len(df),
        "columnas": df.shape[1],
        "clave": clave(nombre, df),
        "tipos": {c: str(t) for c, t in df.dtypes.items()},
        "pct_nulos": {c: float(v) for c, v in nulos.items() if v > 0},
        "mb_csv": round(csv.stat().st_size / 1e6, 3),
        "mb_parquet": round(destino.stat().st_size / 1e6, 3),
        "actualizado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def cargar_catalogo(capa: Capa) -> dict:
    """Catálogo de la capa. Si el JSON está dañado se empieza de cero (se reconvierte todo)."""
    if not capa.catalogo.exists():
        return {}
    try:
        return json.loads(capa.catalogo.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        print(f"AVISO: no se puede leer {capa.catalogo.name} de {capa.value} ({error}); "
              "se vuelven a convertir todos sus datasets")
        return {}


def guardar_catalogo(capa: Capa, catalogo: dict) -> None:
    """Guarda el catálogo de la capa (escritura segura, como los Parquet)."""
    texto = json.dumps(catalogo, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    escribir_seguro(capa.catalogo, lambda t: t.write_text(texto, encoding="utf-8"))


def codigos_maestros(trabajo: Path) -> set | None:
    """Códigos INE de la lista maestra (None si no existe o no se puede leer)."""
    archivo = trabajo / f"{LISTA_MAESTRA}.csv"
    if not archivo.exists():
        return None
    try:
        return set(tipar(leer_csv(archivo))["codigo_ine"].dropna())
    except (KeyError, *ERRORES_DATASET) as error:
        print(f"AVISO: no se puede leer la lista maestra {archivo.name} ({error}); "
              "no se comprobará si los códigos INE existen")
        return None


# ---------------- Conversión ----------------

def otra_capa(capa: Capa) -> Capa:
    return Capa.SILVER if capa is Capa.GOLD else Capa.GOLD


def convertir_dataset(csv: Path, capa: Capa, codigos_validos: set | None, sha: str):
    """Lee, tipa, valida y guarda un CSV. Devuelve (estado, entrada del catálogo o None)."""
    nombre, destino = csv.stem, ruta(csv.stem, capa)
    df = tipar(leer_csv(csv))
    errores, avisos = validar(nombre, df, codigos_validos)
    for aviso in avisos:
        print(f"  ~ {nombre:<36} aviso: {aviso}")
    if errores:
        anterior = " (se mantiene el Parquet anterior, marcado como desactualizado)" \
            if destino.exists() else ""
        for error in errores:
            print(f"  ! {nombre:<36} ERROR: {error}{anterior}")
        return ERROR, None
    guardar_parquet(df, destino)
    ruta(nombre, otra_capa(capa)).unlink(missing_ok=True)   # que no quede una copia vieja
    entrada = describir(nombre, df, csv, destino, capa, sha)
    print(f"  + {nombre:<36} {len(df):>7} filas -> data/{capa.value}/ "
          f"({entrada['mb_csv']} MB en CSV, {entrada['mb_parquet']} MB en Parquet)")
    return CONVERTIDO, entrada


def procesar(csv: Path, capa: Capa, previa: dict | None, codigos_validos: set | None,
             forzar: bool):
    """Convierte un CSV si ha cambiado. Devuelve (estado, entrada nueva del catálogo).
    Un fallo en este dataset no para la conversión de los demás."""
    nombre = csv.stem
    try:
        sha = huella(csv)
        al_dia = (previa and previa.get("sha256") == sha
                  and previa.get("version_esquema") == VERSION_ESQUEMA
                  and not previa.get(MARCA_DESACTUALIZADO))
        if not forzar and al_dia and ruta(nombre, capa).exists():
            print(f"  = {nombre:<36} sin cambios")
            return SIN_CAMBIOS, previa
        estado, entrada = convertir_dataset(csv, capa, codigos_validos, sha)
    except ERRORES_DATASET as error:
        print(f"  ! {nombre:<36} ERROR: {type(error).__name__}: {error}")
        estado, entrada = ERROR, None
    if estado == ERROR:
        entrada = {**previa, MARCA_DESACTUALIZADO: True} if previa else None
    return estado, entrada


def avisar_huerfanos(csvs: list[Path]) -> None:
    """Parquet cuyo CSV ya no está en data/processed/: se avisa, no se borra."""
    nombres = {c.stem for c in csvs}
    for capa in (Capa.SILVER, Capa.GOLD):
        for archivo in sorted(capa.carpeta.glob("*.parquet")):
            if archivo.stem not in nombres:
                print(f"AVISO: data/{capa.value}/{archivo.name} no tiene CSV en "
                      "data/processed/ (puede estar desactualizado)")


def convertir_todo(forzar: bool = False, solo: list[str] | None = None) -> dict[str, str]:
    """Convierte los CSV de data/processed/. Devuelve {nombre: estado}."""
    trabajo = carpeta_trabajo()
    if not trabajo.exists():
        raise FileNotFoundError(f"no existe {trabajo}: ejecuta antes python run_pipeline.py")
    csvs = sorted(trabajo.glob("*.csv"))
    if solo:
        desconocidos = set(solo) - {c.stem for c in csvs}
        if desconocidos:
            print(f"AVISO: no hay CSV para {sorted(desconocidos)} en data/processed/")
    else:
        avisar_huerfanos(csvs)
    elegidos = [c for c in csvs if not solo or c.stem in solo]

    catalogos = {capa: cargar_catalogo(capa) for capa in (Capa.SILVER, Capa.GOLD)}
    codigos_validos = codigos_maestros(trabajo)
    resultado = {}
    try:
        for csv in elegidos:
            nombre = csv.stem
            capa = Capa.GOLD if nombre in DATASETS_GOLD else Capa.SILVER
            capa_previa = capa if nombre in catalogos[capa] else otra_capa(capa)
            previa = catalogos[capa_previa].get(nombre)
            resultado[nombre], entrada = procesar(csv, capa, previa, codigos_validos, forzar)
            if entrada is None:
                continue
            # Con error, la marca de desactualizado va donde sigue el Parquet anterior
            capa_entrada = capa_previa if resultado[nombre] == ERROR else capa
            if capa_entrada is not capa_previa:
                catalogos[capa_previa] = {k: v for k, v in catalogos[capa_previa].items()
                                          if k != nombre}
            catalogos[capa_entrada] = {**catalogos[capa_entrada], nombre: entrada}
    finally:                                  # aunque algo falle, lo convertido queda apuntado
        for capa, catalogo in catalogos.items():
            if catalogo or capa.catalogo.exists():
                guardar_catalogo(capa, catalogo)
    return resultado


def resumen(resultado: dict[str, str]) -> None:
    """Muestra cuántos datasets se han convertido y cuánto ocupan en CSV y en Parquet."""
    cuenta = {e: list(resultado.values()).count(e) for e in (CONVERTIDO, SIN_CAMBIOS, ERROR)}
    entradas = [entrada for capa in (Capa.SILVER, Capa.GOLD)
                for nombre, entrada in cargar_catalogo(capa).items() if nombre in resultado]
    mb_csv = sum(e["mb_csv"] for e in entradas)
    mb_parquet = sum(e["mb_parquet"] for e in entradas)
    print(f"\nResumen: {cuenta[CONVERTIDO]} convertidos, {cuenta[SIN_CAMBIOS]} sin cambios, "
          f"{cuenta[ERROR]} con error")
    if mb_csv:
        print(f"Tamaño: {mb_csv:.1f} MB en CSV -> {mb_parquet:.1f} MB en Parquet "
              f"({(1 - mb_parquet / mb_csv) * 100:.0f} % menos)")
    if cuenta[ERROR]:
        print("Fallaron: " + ", ".join(n for n, e in resultado.items() if e == ERROR))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pasa los CSV limpios a Parquet (Silver y Gold)")
    parser.add_argument("--forzar", action="store_true",
                        help="vuelve a convertir aunque el CSV no haya cambiado")
    parser.add_argument("--solo", nargs="+", metavar="DATASET",
                        help="convierte solo estos datasets (nombre del CSV sin .csv)")
    args = parser.parse_args(argv)
    try:
        resultado = convertir_todo(forzar=args.forzar, solo=args.solo)
    except FileNotFoundError as error:
        print(f"ERROR: {error}")
        return 1
    resumen(resultado)
    return 1 if ERROR in resultado.values() else 0


if __name__ == "__main__":
    sys.exit(main())
