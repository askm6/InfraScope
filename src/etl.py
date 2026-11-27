import sys
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]
PROCESSED = RAIZ / "data" / "processed"

# ---------------- Configuración ----------------
RUTA_MUNICIPIOS = PROCESSED / "municipios.csv"        # lista maestra: codigo_ine, municipio, latitud, longitud
RUTA_SALIDA = PROCESSED / "tabla_integrada.csv"

# Columnas que pasan a la tabla integrada, agrupadas por dataset de origen.
# nombre corto del dataset -> (archivo, {columna en el archivo: nombre en la tabla})
COLUMNAS = {
    # Energía
    "energia": ("energia_municipios.csv", {
        "renovable_pct": "renovable_pct",
        "autoabastecimiento_pct": "autoabastecimiento_pct",
        "demanda_mwh_estimada": "demanda_mwh_estimada",
        "exportacion_neta_mwh_estimada": "exportacion_neta_mwh_estimada",
        "precio_medio_eur_mwh": "precio_medio_eur_mwh",        # precio de la luz
    }),
    # Agua
    "agua": ("agua_suministro_municipios.csv", {
        "coste_unitario_eur_m3": "coste_unitario_eur_m3",      # precio del agua
    }),
    # Socioeconómico
    "poblacion": ("poblacion_municipios.csv", {
        "poblacion": "poblacion",
    }),
    "socioeconomico": ("socioeconomico_municipios.csv", {
        "tasa_paro_aprox": "tasa_paro_aprox",
    }),
    "movilidad_laboral": ("movilidad_laboral_municipios.csv", {
        "porcentaje_trabaja_fuera_municipio": "porcentaje_trabaja_fuera_municipio",
    }),
    # Medioambiente
    "espacios_protegidos": ("espacios_protegidos_municipios.csv", {
        "area_protegida_10km_ha": "area_protegida_10km_ha",
    }),
}

# municipios_limites.csv tiene más recintos que municipios (condominios y territorios sin
# código INE): solo se usan las filas de tipo "municipio" y la superficie.
RUTA_LIMITES = PROCESSED / "municipios_limites.csv"

# Unidad según el final del nombre de la columna (convención de los scripts de limpieza)
UNIDADES = {
    "_pct": "%", "_pp": "puntos porcentuales", "_km": "km", "_km2": "km²", "_ha": "ha",
    "_m2": "m²", "_mwh": "MWh", "_kwh": "kWh", "_eur_mwh": "€/MWh", "_eur_m3": "€/m³",
    "_l_hab_dia": "L/habitante/día", "_m3_km_anio": "m³/km/año", "_g": "g (aceleración)",
    "_hm3": "hm³", "_mw": "MW",
}


def normalizar_codigo(serie):
    """Deja el código INE como texto de 5 cifras: 8019 / 8019.0 / '08019' -> '08019'."""
    texto = serie.astype(str).str.strip().str.replace(r"\.0$", "", regex=True)
    return texto.str.zfill(5)


def leer(ruta):
    """Lee un CSV de data/processed/ con codigo_ine como texto de 5 cifras."""
    df = pd.read_csv(ruta, dtype={"codigo_ine": str}, encoding="utf-8-sig")
    df = df[df["codigo_ine"].notna()].copy()
    df["codigo_ine"] = normalizar_codigo(df["codigo_ine"])
    return df


def preparar(nombre, df, codigos_maestra, columnas):
    """Revisa duplicados y códigos desconocidos y se queda con las columnas pedidas
    (renombradas según el diccionario columnas)."""
    faltan = [c for c in columnas if c not in df.columns]
    if faltan:
        print(f"  AVISO {nombre}: no tiene las columnas {', '.join(faltan)}, se sigue sin ellas")
    duplicados = df["codigo_ine"].duplicated()
    if duplicados.any():
        print(f"  AVISO {nombre}: {duplicados.sum()} códigos repetidos, se queda la primera fila")
        df = df[~duplicados]
    desconocidos = ~df["codigo_ine"].isin(codigos_maestra)
    if desconocidos.any():
        print(f"  AVISO {nombre}: {desconocidos.sum()} códigos no están en municipios.csv, se descartan")
        df = df[~desconocidos]
    presentes = {c: nuevo for c, nuevo in columnas.items() if c in df.columns}
    return df[["codigo_ine"] + list(presentes)].rename(columns=presentes)


def unidad(columna):
    """Unidad deducida del nombre de la columna ('' si el nombre no la indica)."""
    if columna.startswith("pct_") or columna.startswith("porcentaje_"):
        return "%"
    for sufijo, texto in sorted(UNIDADES.items(), key=lambda x: -len(x[0])):
        if columna.endswith(sufijo):
            return texto
    return ""


def informe(tabla, origen):
    """Una fila por columna: origen, tipo, unidad, % de municipios con dato, mínimo y máximo."""
    filas = []
    for col in tabla.columns:
        numerica = pd.api.types.is_numeric_dtype(tabla[col]) and not pd.api.types.is_bool_dtype(tabla[col])
        filas.append({
            "columna": col,
            "origen": origen.get(col, "municipios"),
            "tipo": str(tabla[col].dtype),
            "unidad": unidad(col),
            "pct_municipios_con_dato": round(tabla[col].notna().mean() * 100, 1),
            "minimo": tabla[col].min() if numerica else None,
            "maximo": tabla[col].max() if numerica else None,
        })
    return pd.DataFrame(filas)


def main():
    if not RUTA_MUNICIPIOS.exists():
        print(f"ERROR: falta la lista maestra {RUTA_MUNICIPIOS.relative_to(RAIZ)}. "
              "Genérala con: python run_pipeline.py --solo municipios")
        return 1

    tabla = leer(RUTA_MUNICIPIOS)
    codigos = set(tabla["codigo_ine"])
    # Los 2 primeros dígitos del código INE son la provincia (ver src/territorio.py)
    tabla.insert(1, "codigo_provincia", tabla["codigo_ine"].str[:2])
    print(f"Lista maestra: {len(tabla)} municipios")

    # 1. Superficie del municipio (para el mapa y la densidad de población)
    if RUTA_LIMITES.exists():
        limites = leer(RUTA_LIMITES)
        if "tipo_recinto" in limites.columns:
            limites = limites[limites["tipo_recinto"] == "municipio"]
        limites = preparar("limites", limites, codigos, {"superficie_km2": "superficie_km2"})
        tabla = tabla.merge(limites, on="codigo_ine", how="left", validate="one_to_one")
    else:
        print("  AVISO: falta municipios_limites.csv, la tabla saldrá sin superficie")

    # 2. Unir a la lista maestra las columnas elegidas de cada dataset
    #    (left join: no se pierde ningún municipio)
    origen = {"superficie_km2": "limites"}
    for nombre, (archivo, columnas) in COLUMNAS.items():
        ruta = PROCESSED / archivo
        if not ruta.exists():
            print(f"  AVISO: falta {archivo}, se salta (ejecuta antes run_pipeline.py)")
            continue
        df = preparar(nombre, leer(ruta), codigos, columnas)
        repetidas = [c for c in df.columns if c != "codigo_ine" and c in tabla.columns]
        if repetidas:                         # no debería pasar: los nombres de COLUMNAS son únicos
            print(f"ERROR: {nombre} repite columnas que ya están en la tabla: {', '.join(repetidas)}")
            return 1
        origen.update({c: nombre for c in df.columns if c != "codigo_ine"})
        tabla = tabla.merge(df, on="codigo_ine", how="left", validate="one_to_one")
        con_dato = df["codigo_ine"].nunique()
        print(f"  {nombre:<22} {df.shape[1] - 1:>3} columnas, {con_dato:>5} municipios "
              f"({con_dato / len(codigos) * 100:.1f} %)")

    if len(tabla) != len(codigos):            # no debería pasar gracias a validate
        print(f"ERROR: la tabla tiene {len(tabla)} filas y la lista maestra {len(codigos)}")
        return 1

    # 3. Guardar la tabla y mostrar el resumen de huecos
    tabla.to_csv(RUTA_SALIDA, index=False, encoding="utf-8-sig")
    resumen = informe(tabla, origen)

    incompletas = resumen[resumen["pct_municipios_con_dato"] < 100]
    print(f"\nTabla integrada: {tabla.shape[0]} municipios x {tabla.shape[1]} columnas "
          f"-> {RUTA_SALIDA.relative_to(RAIZ)}")
    print(f"Columnas con huecos: {len(incompletas)} de {len(resumen)}")
    por_origen = incompletas.groupby("origen")["pct_municipios_con_dato"].min().sort_values()
    for nombre, pct in por_origen.items():
        print(f"  {nombre:<22} peor columna con dato en el {pct:.1f} % de municipios")
    return 0


if __name__ == "__main__":
    sys.exit(main())
