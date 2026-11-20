import pandas as pd

try:
    import yaml
except ImportError:                     # sin PyYAML se usan los valores por defecto del CPD
    yaml = None

# ---------------- Configuración ----------------
RUTA_ENTRADA = "data/raw/energia/datadis_consumo_municipios_mensual.csv"
RUTA_PADRON = "data/raw/poblacion/ine_padron_poblacion_municipios_2016_2025.csv"
RUTA_CONFIG = "config/config.yaml"      # potencia y PUE del CPD de referencia

RUTA_SALIDA_MENSUAL = "data/processed/consumo_electrico_mensual.csv"
RUTA_SALIDA_MUNICIPIOS = "data/processed/consumo_electrico_municipios.csv"

SECTORES = {"1": "residencial", "2": "industria", "3": "servicios", "4": "no_especificado"}
# Filas "T": total del mes sin desglose por sector (se usa solo si no hay sectores)
SECTOR_TOTAL = {"T": "total_sin_desglose"}
# Datadis marca los meses más recientes como "piloto": datos provisionales e incompletos
MESES_PILOTO = ["2026-10"]
# Un mes se considera anómalo si su consumo se aleja más de este % de la mediana del municipio
DESVIACION_MAX_PCT = 40
CPD_POR_DEFECTO = {"potencia_ti_mw": 30, "pue": 1.35}
HORAS_ANIO = 8760


def cargar_datos(ruta):
    """Consumo eléctrico mensual por municipio y sector (Datadis, consulta pública)."""
    df = pd.read_csv(ruta, dtype={"codigo_ine": str, "sector": str}, encoding="utf-8")
    for col in ["anio", "mes", "energia_kwh", "contratos"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def limpiar(df):
    """Valores sin dato (-1), duplicados, meses piloto y meses anómalos."""
    filas_inicio = len(df)
    df = df.dropna(subset=["codigo_ine", "anio", "mes", "sector"]).copy()
    df["codigo_ine"] = df["codigo_ine"].str.zfill(5)
    df[["anio", "mes"]] = df[["anio", "mes"]].astype(int)
    df["sector"] = df["sector"].str.strip().str.upper().map({**SECTORES, **SECTOR_TOTAL})
    df = df.dropna(subset=["sector"])
    # Datadis devuelve -1 cuando no hay dato
    for col in ["energia_kwh", "contratos"]:
        df.loc[df[col] < 0, col] = pd.NA
    df = df.drop_duplicates(subset=["codigo_ine", "anio", "mes", "sector"], keep="last")

    # De formato largo (una fila por sector) a una fila por municipio y mes
    ancho = df.pivot_table(index=["codigo_ine", "municipio", "anio", "mes"], columns="sector",
                           values="energia_kwh", aggfunc="sum", min_count=1).reset_index()
    ancho.columns.name = None
    # pivot_table quita los meses sin ningún dato: se recuperan para marcarlos como "sin_dato"
    claves = df[["codigo_ine", "municipio", "anio", "mes"]].drop_duplicates()
    ancho = claves.merge(ancho, on=["codigo_ine", "municipio", "anio", "mes"], how="left")
    for s in list(SECTORES.values()) + list(SECTOR_TOTAL.values()):
        if s not in ancho:
            ancho[s] = pd.NA
    sectores = list(SECTORES.values())
    # Total = suma de sectores; si el mes solo tiene el total sin desglose, se usa ese
    ancho["total_kwh"] = ancho[sectores].sum(axis=1, min_count=1).fillna(ancho["total_sin_desglose"])
    # Contratos: con desglose se suman los sectores; sin desglose, el valor del total
    con_sector = df[df["sector"] != "total_sin_desglose"]
    contratos = con_sector.groupby(["codigo_ine", "anio", "mes"])["contratos"].sum(min_count=1)
    solo_total = df[df["sector"] == "total_sin_desglose"].set_index(["codigo_ine", "anio", "mes"])["contratos"]
    contratos = contratos.combine_first(solo_total)
    ancho = ancho.merge(contratos.rename("contratos").reset_index(), on=["codigo_ine", "anio", "mes"])

    # Estado de cada mes
    ancho["periodo"] = ancho["anio"].astype(str) + "-" + ancho["mes"].astype(str).str.zfill(2)
    ancho["estado"] = "ok"
    ancho.loc[ancho["total_kwh"].isna(), "estado"] = "sin_dato"
    ancho.loc[ancho["periodo"].isin(MESES_PILOTO), "estado"] = "piloto"
    # Mes anómalo: se aleja a la vez de la mediana del municipio y del mismo mes en los
    # demás años. Así los picos de verano (que se repiten cada año) no se marcan como error.
    ok = ancho["estado"] == "ok"
    mediana = ancho[ok].groupby("codigo_ine")["total_kwh"].median()
    desv_general = (ancho["total_kwh"] / ancho["codigo_ine"].map(mediana) - 1).abs() * 100

    def mediana_otros_anios(fila):
        otros = ancho[ok & (ancho["codigo_ine"] == fila["codigo_ine"]) & (ancho["mes"] == fila["mes"])
                      & (ancho["anio"] != fila["anio"])]["total_kwh"]
        return otros.median() if len(otros) else fila["total_kwh"]

    mismo_mes = ancho[ok].apply(mediana_otros_anios, axis=1).reindex(ancho.index)
    desv_mes = (ancho["total_kwh"] / mismo_mes - 1).abs() * 100
    anomalo = ok & (desv_general > DESVIACION_MAX_PCT) & (desv_mes.fillna(0) > DESVIACION_MAX_PCT)
    ancho.loc[anomalo, "estado"] = "anomalo"

    print(f"Filas: {filas_inicio} leídas -> {len(ancho)} meses-municipio "
          f"({ancho['codigo_ine'].nunique()} municipios, {ancho['periodo'].min()} a {ancho['periodo'].max()})")
    print(f"Estado de los meses: {ancho['estado'].value_counts().to_dict()}")
    huecos = ancho[ancho["estado"] == "sin_dato"].groupby("periodo")["codigo_ine"].count()
    if len(huecos):
        print(f"Meses sin dato (nº de municipios afectados): {huecos.to_dict()}")
    columnas = ["codigo_ine", "municipio", "anio", "mes", "periodo", "estado", "total_kwh"] + sectores + ["contratos"]
    return ancho.sort_values(["codigo_ine", "anio", "mes"])[columnas].reset_index(drop=True)


def potencia_cpd(ruta_config):
    """Consumo anual del CPD de referencia (MWh) = potencia TI x PUE x 8.760 h."""
    cpd = dict(CPD_POR_DEFECTO)
    if yaml is not None:
        try:
            with open(ruta_config, encoding="utf-8") as f:
                ref = yaml.safe_load(f).get("cpd_referencia", {})
            cpd.update({k: ref[k] for k in cpd if k in ref})
        except FileNotFoundError:
            print(f"Aviso: no se encuentra {ruta_config}, se usa el CPD por defecto")
    return cpd["potencia_ti_mw"] * cpd["pue"] * HORAS_ANIO, cpd


def resumir_municipios(mensual, ruta_padron, ruta_config):
    """Consumo anual por municipio con el último año completo, reparto por sectores,
    consumo por habitante y peso que tendría el CPD de referencia sobre el consumo local."""
    validos = mensual[mensual["estado"] == "ok"]
    # Para el reparto por sectores el año de referencia debe tener desglose
    con_desglose = validos[validos["industria"].notna()]
    meses = con_desglose.groupby(["codigo_ine", "anio"])["mes"].nunique()
    completos = meses[meses == 12].reset_index()
    if completos.empty:
        raise ValueError("No hay ningún año completo (12 meses válidos) para resumir")
    anio_ref = completos.groupby("anio")["codigo_ine"].nunique().idxmax()
    print(f"Año de referencia (más municipios con 12 meses válidos): {anio_ref}")

    sectores = list(SECTORES.values())
    anual = validos[validos["anio"] == anio_ref].groupby(["codigo_ine", "municipio"]).agg(
        meses_validos=("mes", "nunique"), total_kwh=("total_kwh", "sum"),
        contratos=("contratos", "mean"), **{s: (s, lambda x: x.sum(min_count=1)) for s in sectores}).reset_index()
    # Si a algún municipio le faltan meses, se anualiza con la media de los que tiene
    factor = 12 / anual["meses_validos"]
    for col in ["total_kwh"] + sectores:
        anual[col] = anual[col] * factor
    incompletos = anual[anual["meses_validos"] < 12]
    if len(incompletos):
        print(f"Aviso: anualizados por faltar meses: {list(incompletos['municipio'])}")

    res = anual[["codigo_ine", "municipio", "meses_validos"]].copy()
    res.insert(2, "anio", anio_ref)
    res["consumo_total_mwh"] = (anual["total_kwh"] / 1000).round(0)
    for s in sectores:
        res[f"pct_{s}"] = (anual[s] / anual["total_kwh"] * 100).round(1)
    res["contratos_medios"] = anual["contratos"].round(0)
    res["kwh_por_contrato"] = (anual["total_kwh"] / anual["contratos"]).round(0)

    # Evolución: mismo cálculo con el año anterior (si tiene 12 meses válidos)
    previo = validos[validos["anio"] == anio_ref - 1].groupby("codigo_ine").agg(
        n=("mes", "nunique"), total=("total_kwh", "sum"))
    previo = previo[previo["n"] == 12]["total"] / 1000
    res["var_interanual_pct"] = ((res["consumo_total_mwh"] / res["codigo_ine"].map(previo) - 1) * 100).round(2)

    # Por habitante (padrón del mismo año o el más reciente disponible)
    padron = pd.read_csv(ruta_padron, dtype={"codigo_ine": str}, encoding="utf-8-sig",
                         usecols=["codigo_ine", "anio", "poblacion"])
    anio_pob = min(anio_ref, padron["anio"].max())
    pob = padron[padron["anio"] == anio_pob].set_index("codigo_ine")["poblacion"]
    res["poblacion"] = res["codigo_ine"].map(pob)
    res["mwh_por_habitante"] = (res["consumo_total_mwh"] / res["poblacion"]).round(2)

    # Impacto del CPD de referencia sobre el consumo eléctrico del municipio
    cpd_mwh, cpd = potencia_cpd(ruta_config)
    res["cpd_referencia_mwh"] = round(cpd_mwh)
    res["impacto_cpd_pct"] = (cpd_mwh / res["consumo_total_mwh"] * 100).round(1)
    print(f"CPD de referencia: {cpd['potencia_ti_mw']} MW TI x PUE {cpd['pue']} = {cpd_mwh:,.0f} MWh/año")
    return res.sort_values("consumo_total_mwh", ascending=False).reset_index(drop=True)


if __name__ == "__main__":
    mensual = limpiar(cargar_datos(RUTA_ENTRADA))
    municipios = resumir_municipios(mensual, RUTA_PADRON, RUTA_CONFIG)

    mensual.to_csv(RUTA_SALIDA_MENSUAL, index=False, encoding="utf-8-sig")
    municipios.to_csv(RUTA_SALIDA_MUNICIPIOS, index=False, encoding="utf-8-sig")

    columnas = ["municipio", "consumo_total_mwh", "pct_industria", "pct_servicios", "mwh_por_habitante",
                "var_interanual_pct", "impacto_cpd_pct"]
    print("\nConsumo anual por municipio:")
    print(municipios[columnas].to_string(index=False))
    print(f"\nGuardado: {RUTA_SALIDA_MENSUAL}, {RUTA_SALIDA_MUNICIPIOS}")
