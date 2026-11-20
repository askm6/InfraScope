import numpy as np
import pandas as pd

# ---------------- Configuración ----------------
RUTA_PEERINGDB = "data/raw/telecomunicaciones/peeringdb_cpd_existentes_espana.csv"
RUTA_OSM = "data/raw/telecomunicaciones/osm_cpd_espana.csv"
RUTA_MUNICIPIOS = "data/processed/municipios.csv"      # lista maestra: codigo_ine, municipio, latitud, longitud

RUTA_SALIDA_CPD = "data/processed/cpd_existentes.csv"
RUTA_SALIDA_MUNICIPIOS = "data/processed/cpd_municipios.csv"

# PeeringDB solo trae los CPD con interconexión (colocation). OpenStreetMap añade los
# corporativos, públicos y de los grandes de la nube. Juntamos las dos fuentes.
DISTANCIA_MISMO_SITIO_KM = 0.25        # registros a menos de 250 m = mismo emplazamiento (campus)
RADIOS_KM = [10, 50]
LIMITES_ESPANA = {"lat": (27.0, 44.5), "lon": (-18.5, 4.5)}   # península, Baleares y Canarias

# Nombres de ciudad que llegan en inglés o con variantes
CIUDADES = {"Seville": "Sevilla", "Valencia": "València", "San Sebastián": "Donostia/San Sebastián"}

# Tipo de CPD según el operador o el nombre (se busca el texto, sin distinguir mayúsculas)
TIPOS_CPD = [
    ("hiperescala", r"amazon|aws|microsoft|google|meta platforms|oracle cloud"),
    ("publico", r"gobierno|gobienro|nasertic|consejo superior|csic|csuc|universi|ayuntamiento|junta de"),
    ("corporativo", r"banco|santander|ibm|telefónica|inforland|mozoilo"),
]


def haversine_km(lat1, lon1, lat2, lon2):
    """Distancia en km entre puntos (admite arrays de numpy)."""
    lat1, lon1, lat2, lon2 = map(np.radians, [lat1, lon1, lat2, lon2])
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 6371.0088 * 2 * np.arcsin(np.sqrt(a))


def cargar_peeringdb(ruta):
    """CPD de PeeringDB, con el formato común."""
    df = pd.read_csv(ruta, dtype={"fac_id": str, "cp": str}, encoding="utf-8-sig")
    df = df[df["estado"].fillna("ok").str.strip() == "ok"]
    return pd.DataFrame({
        "id_origen": "peeringdb/" + df["fac_id"],
        "fuente": "peeringdb",
        "nombre": df["nombre"],
        "operador": df["organizacion"],
        "ciudad": df["ciudad"],
        "latitud": pd.to_numeric(df["latitud"], errors="coerce"),
        "longitud": pd.to_numeric(df["longitud"], errors="coerce"),
        "num_redes": pd.to_numeric(df["num_redes"], errors="coerce"),
        "num_ix": pd.to_numeric(df["num_ix"], errors="coerce"),
        "num_carriers": pd.to_numeric(df["num_carriers"], errors="coerce"),
    })


def cargar_osm(ruta):
    """CPD de OpenStreetMap (telecom=data_center o building=data_center), con el formato común."""
    df = pd.read_csv(ruta, dtype=str, encoding="utf-8", keep_default_na=False)
    return pd.DataFrame({
        "id_origen": "osm/" + df["osm_id"],
        "fuente": "osm",
        "nombre": df["nombre"].replace("", pd.NA),
        "operador": df["operador"].replace("", pd.NA),
        "ciudad": df["ciudad"].replace("", pd.NA),
        "latitud": pd.to_numeric(df["latitud"], errors="coerce"),
        "longitud": pd.to_numeric(df["longitud"], errors="coerce"),
    })


def limpiar(df):
    """Textos, ciudades, coordenadas fuera de España y tipo de CPD."""
    filas_inicio = len(df)
    df = df.copy()
    for col in ["nombre", "operador", "ciudad"]:
        df[col] = df[col].astype("string").str.strip().str.replace(r"\s+", " ", regex=True)
        df[col] = df[col].str.rstrip(" !")
    df["ciudad"] = df["ciudad"].replace(CIUDADES)

    sin_coord = df["latitud"].isna() | df["longitud"].isna()
    fuera = ~df["latitud"].between(*LIMITES_ESPANA["lat"]) | ~df["longitud"].between(*LIMITES_ESPANA["lon"])
    df["coordenadas_validas"] = ~(sin_coord | fuera)
    if (~df["coordenadas_validas"]).any():
        print(f"Aviso: {(~df['coordenadas_validas']).sum()} CPD sin coordenadas válidas "
              f"(se guardan, pero no cuentan en las distancias):")
        print(df.loc[~df["coordenadas_validas"], ["id_origen", "nombre", "ciudad"]].to_string(index=False))

    texto = (df["operador"].fillna("") + " " + df["nombre"].fillna("")).str.lower()
    df["tipo_cpd"] = "colocation"
    for tipo, patron in reversed(TIPOS_CPD):
        df.loc[texto.str.contains(patron, regex=True), "tipo_cpd"] = tipo
    df.loc[df["nombre"].isna() & df["operador"].isna(), "tipo_cpd"] = "desconocido"

    df = df.drop_duplicates(subset=["id_origen"])
    print(f"Registros: {filas_inicio} leídos -> {len(df)} limpios "
          f"({(df['fuente'] == 'peeringdb').sum()} PeeringDB, {(df['fuente'] == 'osm').sum()} OSM)")
    return df.reset_index(drop=True)


def agrupar_emplazamientos(df, umbral_km=DISTANCIA_MISMO_SITIO_KM):
    """Une los registros que están a menos de `umbral_km` (mismo CPD en las dos fuentes,
    varios edificios del mismo campus o varias empresas dentro del mismo edificio)."""
    validos = df[df["coordenadas_validas"]].reset_index(drop=True)
    lat, lon = validos["latitud"].to_numpy(), validos["longitud"].to_numpy()
    dist = haversine_km(lat[:, None], lon[:, None], lat[None, :], lon[None, :])

    # Unión de grupos (union-find) con los pares cercanos
    padre = list(range(len(validos)))

    def raiz(i):
        while padre[i] != i:
            padre[i] = padre[padre[i]]
            i = padre[i]
        return i

    for i, j in zip(*np.where(np.triu(dist <= umbral_km, k=1))):
        padre[raiz(i)] = raiz(j)
    validos["grupo"] = [raiz(i) for i in range(len(validos))]

    filas = []
    for _, g in validos.groupby("grupo"):
        # Nombre principal: el CPD de PeeringDB con más redes (el edificio "ancla");
        # si solo hay datos de OSM, el nombre más largo (suele ser el más descriptivo)
        con_nombre = g.dropna(subset=["nombre"])
        pdb = con_nombre[con_nombre["fuente"] == "peeringdb"]
        if len(pdb):
            principal = pdb.sort_values("num_redes", ascending=False)
        else:
            principal = con_nombre.sort_values("nombre", key=lambda s: s.str.len(), ascending=False)
        tipos = [t for t in ["hiperescala", "publico", "corporativo", "colocation"] if t in set(g["tipo_cpd"])]
        filas.append({
            "nombre": principal["nombre"].iloc[0] if len(principal) else "(sin nombre)",
            "operadores": "; ".join(sorted(set(g["operador"].dropna()))) or pd.NA,
            "ciudad": g["ciudad"].dropna().iloc[0] if g["ciudad"].notna().any() else pd.NA,
            "latitud": round(g["latitud"].mean(), 6),
            "longitud": round(g["longitud"].mean(), 6),
            "tipo_cpd": tipos[0] if tipos else "desconocido",
            "fuentes": "+".join(sorted(set(g["fuente"]))),
            "n_registros": len(g),
            "num_redes": g["num_redes"].max(),
            "num_ix": g["num_ix"].max(),
            "num_carriers": g["num_carriers"].max(),
            "ids_origen": "; ".join(g["id_origen"]),
        })
    res = pd.DataFrame(filas)

    # Los que no tienen coordenadas se añaden tal cual al final
    sin = df[~df["coordenadas_validas"]]
    if len(sin):
        res = pd.concat([res, pd.DataFrame({
            "nombre": sin["nombre"], "operadores": sin["operador"], "ciudad": sin["ciudad"],
            "tipo_cpd": sin["tipo_cpd"], "fuentes": sin["fuente"], "n_registros": 1,
            "num_redes": sin["num_redes"], "num_ix": sin["num_ix"], "num_carriers": sin["num_carriers"],
            "ids_origen": sin["id_origen"]})], ignore_index=True)

    res = res.sort_values(["num_redes", "nombre"], ascending=[False, True], na_position="last")
    res.insert(0, "id_cpd", [f"CPD{i:03d}" for i in range(1, len(res) + 1)])
    print(f"Emplazamientos: {len(res)} ({(res['fuentes'] == 'osm+peeringdb').sum()} confirmados por las dos "
          f"fuentes); por tipo: {res['tipo_cpd'].value_counts().to_dict()}")
    return res.reset_index(drop=True)


def resumir_municipios(cpd, ruta_municipios):
    """Cercanía de cada municipio al ecosistema de CPD: más CPD y redes cerca = más
    conectividad y proveedores, pero también más competencia por la potencia eléctrica."""
    muni = pd.read_csv(ruta_municipios, dtype={"codigo_ine": str}, encoding="utf-8")
    con = cpd.dropna(subset=["latitud", "longitud"])
    dist = haversine_km(muni["latitud"].to_numpy()[:, None], muni["longitud"].to_numpy()[:, None],
                        con["latitud"].to_numpy()[None, :], con["longitud"].to_numpy()[None, :])

    res = muni[["codigo_ine", "municipio"]].copy()
    cerca = dist.argmin(axis=1)
    res["cpd_mas_cercano"] = con["nombre"].to_numpy()[cerca]
    res["dist_cpd_km"] = dist.min(axis=1).round(2)
    redes = con["num_redes"].fillna(0).to_numpy()
    hiper = (con["tipo_cpd"] == "hiperescala").to_numpy()
    for r in RADIOS_KM:
        dentro = dist <= r
        res[f"n_cpd_{r}km"] = dentro.sum(axis=1)
        res[f"redes_max_{r}km"] = np.where(dentro, redes, 0).max(axis=1).astype(int)
    res["n_hiperescala_50km"] = (dist <= 50)[:, hiper].sum(axis=1)
    return res.sort_values("n_cpd_50km", ascending=False).reset_index(drop=True)


if __name__ == "__main__":
    registros = limpiar(pd.concat([cargar_peeringdb(RUTA_PEERINGDB), cargar_osm(RUTA_OSM)], ignore_index=True))
    cpd = agrupar_emplazamientos(registros)
    municipios = resumir_municipios(cpd, RUTA_MUNICIPIOS)

    cpd.to_csv(RUTA_SALIDA_CPD, index=False, encoding="utf-8-sig")
    municipios.to_csv(RUTA_SALIDA_MUNICIPIOS, index=False, encoding="utf-8-sig")

    print("\nCPD con más redes conectadas:")
    print(cpd[["id_cpd", "nombre", "ciudad", "tipo_cpd", "fuentes", "num_redes"]].head(10).to_string(index=False))
    print("\nMunicipios por número de CPD a 50 km:")
    print(municipios.to_string(index=False))
    print(f"\nGuardado: {RUTA_SALIDA_CPD}, {RUTA_SALIDA_MUNICIPIOS}")
