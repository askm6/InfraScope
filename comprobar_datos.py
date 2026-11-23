"""Comprueba que los datos de data/processed/ están bien después de ejecutar el pipeline.

Uso (desde la raíz del proyecto):
    python run_pipeline.py          # primero, genera los datos
    python comprobar_datos.py       # después, los comprueba

Qué comprueba:
  1. Que existen los archivos esperados y no quedan los antiguos por comunidad/provincia.
  2. Que municipios.csv es la lista maestra: códigos de 5 cifras, sin duplicados y con
     coordenadas.
  3. Que cada *_municipios.csv tiene una fila por municipio de la lista maestra (los mismos
     códigos, sin duplicados) y qué % de municipios tiene datos.
  4. Que ningún CSV tiene columnas de provincia o comunidad autónoma.
  5. Que los totales cuadran con cifras oficiales conocidas (población, paro).
  6. Si existe la copia ../Proyecto3_backup_processed/, que los municipios que ya tenían
     datos conservan los mismos valores (es informativo: algunas diferencias son esperadas).

Termina con código 1 si alguna comprobación FALLA (los AVISOS no cuentan como fallo).
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

RAIZ = Path(__file__).resolve().parent
PROCESSED = RAIZ / "data" / "processed"
COPIA = RAIZ.parent / "Proyecto3_backup_processed"

# Archivos que deben existir (una fila por municipio)
POR_MUNICIPIO = [
    "aeropuertos_municipios", "agua_suministro_municipios", "cpd_municipios",
    "energia_municipios", "espacios_protegidos_municipios", "poblacion_municipios",
    "proyeccion_poblacion_municipios", "socioeconomico_municipios", "movilidad_laboral_municipios",
    # Aún con 29 municipios (puntos B, C y E pendientes): se avisa, no falla
    "cobertura_municipios", "riesgos_municipios",
]
PENDIENTES = {"cobertura_municipios", "riesgos_municipios"}
# Archivos con una fila por municipio y año
POR_MUNICIPIO_Y_ANIO = ["paro_municipios", "socioeconomico_anual"]
# Archivo con una fila por municipio y tasa anual de emigración intermunicipal
MOVILIDAD = "movilidad_laboral_municipios"
# Archivos que ya no deben existir (eran por comunidad o provincia)
OBSOLETOS = ["energia_ccaa_anual", "energia_ccaa_mensual", "energia_picos_precio",
             "agua_suministro_ccaa_anual", "poblacion_provincias",
             "proyeccion_poblacion_anual", "proyeccion_poblacion_provincias", "paro_provincias"]
PALABRAS_PROHIBIDAS = ["provincia", "ccaa", "comunidad"]

resultados = []          # (estado, comprobación, detalle)


def anotar(ok, comprobacion, detalle="", aviso=False):
    estado = "OK" if ok else ("AVISO" if aviso else "FALLO")
    resultados.append((estado, comprobacion, detalle))


def leer(nombre, carpeta=PROCESSED):
    return pd.read_csv(carpeta / f"{nombre}.csv", dtype={"codigo_ine": str}, encoding="utf-8-sig")


def columnas_de_datos(df):
    return [c for c in df.columns if c not in ("codigo_ine", "municipio", "anio", "ranking")]


def comprobar_archivos():
    for nombre in POR_MUNICIPIO + POR_MUNICIPIO_Y_ANIO + ["municipios"]:
        anotar((PROCESSED / f"{nombre}.csv").exists(), f"existe {nombre}.csv")
    for nombre in OBSOLETOS:
        anotar(not (PROCESSED / f"{nombre}.csv").exists(), f"no queda {nombre}.csv (obsoleto)")


def comprobar_maestra():
    m = leer("municipios")
    anotar(len(m) > 8000, "municipios.csv: lista completa", f"{len(m)} municipios")
    anotar(m["codigo_ine"].str.fullmatch(r"\d{5}").all(), "municipios.csv: códigos de 5 cifras")
    anotar(not m["codigo_ine"].duplicated().any(), "municipios.csv: sin códigos duplicados")
    sin = m[["latitud", "longitud"]].isna().any(axis=1).sum()
    anotar(sin == 0, "municipios.csv: todos con coordenadas", f"{sin} sin coordenadas")
    return set(m["codigo_ine"])


def comprobar_por_municipio(maestra):
    for nombre in POR_MUNICIPIO:
        if not (PROCESSED / f"{nombre}.csv").exists():
            continue
        df = leer(nombre)
        pendiente = nombre in PENDIENTES
        anotar(not df["codigo_ine"].duplicated().any(), f"{nombre}: sin duplicados")
        anotar(set(df["codigo_ine"]) == maestra, f"{nombre}: mismos municipios que la lista maestra",
               f"{df['codigo_ine'].nunique()} de {len(maestra)}", aviso=pendiente)
        con_datos = df[columnas_de_datos(df)].notna().any(axis=1).mean() * 100
        anotar(con_datos > 95, f"{nombre}: municipios con datos", f"{con_datos:.1f} %", aviso=pendiente)


def comprobar_por_municipio_y_anio(maestra):
    for nombre in POR_MUNICIPIO_Y_ANIO:
        if not (PROCESSED / f"{nombre}.csv").exists():
            continue
        df = leer(nombre)
        anotar(not df.duplicated(["codigo_ine", "anio"]).any(), f"{nombre}: sin duplicados (municipio, año)")
        anotar(set(df["codigo_ine"]) == maestra, f"{nombre}: mismos municipios que la lista maestra",
               f"{df['codigo_ine'].nunique()} municipios, años {df['anio'].min()}-{df['anio'].max()}")


def comprobar_movilidad_laboral(maestra):
    """Comprueba el porcentaje de ocupados que trabajan fuera del municipio."""
    if not (PROCESSED / f"{MOVILIDAD}.csv").exists():
        anotar(False, f"existe {MOVILIDAD}.csv")
        return
    df = leer(MOVILIDAD)
    anotar(not df["codigo_ine"].duplicated().any(), f"{MOVILIDAD}: una fila por municipio")
    anotar(set(df["codigo_ine"]) == maestra, f"{MOVILIDAD}: municipios completos",
           f"{df['codigo_ine'].nunique()} municipios")
    pct = df["porcentaje_trabaja_fuera_municipio"]
    anotar(pct.dropna().between(0, 100).all(), f"{MOVILIDAD}: porcentajes entre 0 y 100")

def comprobar_columnas():
    for ruta in sorted(PROCESSED.glob("*.csv")):
        cols = pd.read_csv(ruta, nrows=0, encoding="utf-8-sig").columns
        malas = [c for c in cols if any(p in c.lower() for p in PALABRAS_PROHIBIDAS)]
        if malas:
            anotar(False, f"{ruta.name}: sin columnas de provincia/comunidad", str(malas))
    if not any(r[1].endswith("sin columnas de provincia/comunidad") for r in resultados):
        anotar(True, "ningún CSV tiene columnas de provincia o comunidad")


def comprobar_totales():
    """Cifras oficiales aproximadas: población a 1-1-2025 unos 49 millones; paro registrado
    medio de 2024 unos 2,6 millones."""
    if (PROCESSED / "poblacion_municipios.csv").exists():
        total = leer("poblacion_municipios")["poblacion"].sum()
        anotar(48e6 < total < 51e6, "población total de España razonable", f"{total:,.0f}")
    if (PROCESSED / "paro_municipios.csv").exists():
        paro = leer("paro_municipios")
        total = paro[paro["anio"] == 2024]["paro_medio_anual"].sum()
        anotar(2.4e6 < total < 2.8e6, "paro registrado medio 2024 razonable", f"{total:,.0f}")


def comprobar_copia():
    """Compara con la copia de seguridad los municipios que ya tenían datos en ella."""
    if not COPIA.exists():
        anotar(True, "copia de seguridad", "no hay copia: se salta", aviso=True)
        return
    for nombre in POR_MUNICIPIO:
        if not ((COPIA / f"{nombre}.csv").exists() and (PROCESSED / f"{nombre}.csv").exists()):
            continue
        viejo, nuevo = leer(nombre, COPIA), leer(nombre)
        comunes = [c for c in columnas_de_datos(viejo) if c in nuevo.columns]
        if not comunes:
            continue
        viejo = viejo[viejo[comunes].notna().any(axis=1)].set_index("codigo_ine")
        nuevo = nuevo.set_index("codigo_ine").reindex(viejo.index)
        distintos = 0
        for c in comunes:
            a, b = viejo[c], nuevo[c]
            an, bn = pd.to_numeric(a, errors="coerce"), pd.to_numeric(b, errors="coerce")
            iguales = (np.isclose(an, bn, atol=1e-6) & an.notna()) | (a.astype(str) == b.astype(str)) | a.isna()
            distintos += int((~iguales).sum())
        total = len(viejo) * len(comunes)
        anotar(distintos == 0, f"{nombre}: valores iguales a la copia",
               f"{total - distintos}/{total} valores iguales en {len(viejo)} municipios", aviso=True)


if __name__ == "__main__":
    if not (PROCESSED / "municipios.csv").exists():
        sys.exit("No hay data/processed/municipios.csv: ejecuta antes python run_pipeline.py")
    comprobar_archivos()
    maestra = comprobar_maestra()
    comprobar_por_municipio(maestra)
    comprobar_por_municipio_y_anio(maestra)
    comprobar_movilidad_laboral(maestra)
    comprobar_columnas()
    comprobar_totales()
    comprobar_copia()

    for estado, comprobacion, detalle in resultados:
        print(f"[{estado:5}] {comprobacion}" + (f"  ({detalle})" if detalle else ""))
    fallos = sum(e == "FALLO" for e, _, _ in resultados)
    avisos = sum(e == "AVISO" for e, _, _ in resultados)
    print(f"\n{len(resultados)} comprobaciones: {fallos} fallos, {avisos} avisos")
    sys.exit(1 if fallos else 0)
