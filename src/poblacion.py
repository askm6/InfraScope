import pandas as pd
 
# ---------------- Configuración ----------------
RUTA_ENTRADA = "data/raw/poblacion/poblacion.csv"
RUTA_SALIDA = "data/processed/poblacion_provincias.csv"
MINIMO_HABITANTES = 200000          
ANIO = None                    
 
 
def cargar_datos(ruta):
    """Lee el CSV del INE (tabla poblacion) y pone nombres de columnas cómodos."""
    df = pd.read_csv(ruta, sep="\t", encoding="utf-8-sig", dtype=str, keep_default_na=False)
    columnas = {df.columns[-1]: "poblacion"}
    for col in df.columns:
        if col.startswith("Comunidades"):
            columnas[col] = "ccaa"
        elif col.startswith("Provincias"):
            columnas[col] = "provincia"
        elif col.startswith("Sexo"):
            columnas[col] = "sexo"
        elif col.startswith("Periodo"):
            columnas[col] = "anio"
    df = df.rename(columns=columnas)
 
    # "7.113.886" -> 7113886 (el INE usa el punto para los miles)
    df["poblacion"] = pd.to_numeric(df["poblacion"].str.replace(".", "", regex=False),
                                    errors="coerce")
    df["anio"] = pd.to_numeric(df["anio"], errors="coerce")
    return df.dropna(subset=["poblacion", "anio"]).astype({"anio": int})
 
 
def limpiar(df, anio=None):
    """Solo filas de provincia, ambos sexos y un único año."""
    df = df[df["provincia"].str.strip() != ""]      # fuera totales nacionales y de CCAA
    df = df[df["sexo"] == "Total"]
    df = df[df["anio"] == (anio or df["anio"].max())]
    df = df.drop_duplicates(subset=["provincia", "anio"]).copy()
 
    # "08 Barcelona" -> codigo = "08", nombre = "Barcelona"
    df[["codigo", "nombre"]] = df["provincia"].str.split(" ", n=1, expand=True)
    df["ccaa"] = df["ccaa"].str.split(" ", n=1).str[1]
    return df[["codigo", "nombre", "ccaa", "anio", "poblacion"]]
 
 
def calcular(df):
    """Añade el % sobre el total de España y el ranking."""
    df = df.sort_values("poblacion", ascending=False).reset_index(drop=True)
    df["pct_espana"] = (df["poblacion"] / df["poblacion"].sum() * 100).round(2)
    df.insert(0, "ranking", range(1, len(df) + 1))
    return df
 
 
if __name__ == "__main__":
    resultado = calcular(limpiar(cargar_datos(RUTA_ENTRADA), ANIO))
    seleccion = resultado[resultado["poblacion"] >= MINIMO_HABITANTES]
    seleccion.to_csv(RUTA_SALIDA, index=False, encoding="utf-8-sig")
 
    print(f"Año: {resultado['anio'].iloc[0]}")
    print(f"Provincias analizadas: {len(resultado)}")
    print(f"Población total: {resultado['poblacion'].sum():,}".replace(",", "."))
    print(f"Con al menos {MINIMO_HABITANTES:,} habitantes: {len(seleccion)}")
    print(seleccion.head(15).to_string(index=False))
    print(f"\nResultado guardado en {RUTA_SALIDA}")