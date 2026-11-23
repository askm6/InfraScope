"""Ejecuta con una sola orden todos los scripts de limpieza de datos.

Uso:
    python run_pipeline.py                      # descarga lo que falte (salvo AEMET) y limpia todo
    python run_pipeline.py --descargar          # antes vuelve a descargar todo (AEMET, REE, SEPE,
                                                # INE y Natura 2000)
    python run_pipeline.py --solo agua energia  # solo los scripts indicados
    python run_pipeline.py --lista              # muestra los scripts disponibles

Los datos de origen están en data/raw/ y los resultados se guardan en data/processed/.
"""
import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
RUTA_MUNICIPIOS = RAIZ / "data" / "processed" / "municipios.csv"

# Descargas desde APIs. Sin --descargar solo se ejecutan si falta alguno de sus
# archivos en data/raw/ (tardan y AEMET necesita la API key en el archivo .env).
DESCARGAS = {
    "aemet_descarga": "Clima de AEMET (necesita AEMET_API_KEY en .env)",
    "ree_precios_descarga": "Precios horarios de la electricidad (REE)",
    "ree_ccaa_mensual_descarga": "Demanda y generación mensual por comunidad (REE)",
    "paro_descarga": "Paro registrado mensual de todos los municipios (SEPE)",
    "socioeconomico_descarga": "Renta y demografía de todos los municipios (INE)",
    "natura2000_descarga": "Red Natura 2000 (MITECO) y mapa de tierra (Natural Earth)",
    "movilidad_laboral_descarga": "Matriz de residencia y trabajo del INE",
}

# Archivos que deja cada descarga: si falta alguno, hay que descargar
ARCHIVOS_DESCARGA = {
    "aemet_descarga": ["data/raw/aemet/aemet_mensual.csv",
                       "data/raw/aemet/municipio_estacion.csv"],
    "ree_precios_descarga": ["data/raw/energia/ree_precios_horarios.csv"],
    "ree_ccaa_mensual_descarga": ["data/raw/energia/ree_demanda_ccaa_mensual.csv",
                                  "data/raw/energia/ree_generacion_renovable_ccaa_mensual.csv"],
    "paro_descarga": ["data/raw/socioeconomico/paro_municipios_sepe_mensual.csv"],
    "socioeconomico_descarga": ["data/raw/socioeconomico/ine_renta_media_municipios.csv",
                                "data/raw/socioeconomico/ine_indicadores_demograficos_municipios.csv"],
    "natura2000_descarga": ["data/raw/medioambiente/miteco_rednatura2000_2025_gml.zip",
                            "data/raw/medioambiente/naturalearth_10m_tierra.geojson"],
    "movilidad_laboral_descarga": ["data/raw/trabajo/matriz_residencia_trabajo_2023.xlsb"],
}


# Descargas que nunca se lanzan solas (solo con --descargar o --solo): la de AEMET
# tarda mucho y llena data/raw/aemet/ de JSON intermedios
SOLO_A_MANO = {"aemet_descarga"}


def faltan_datos(nombre):
    """True si a la descarga le falta alguno de sus archivos en data/raw/."""
    return any(not (RAIZ / ruta).exists() for ruta in ARCHIVOS_DESCARGA.get(nombre, []))

# Limpieza: lee data/raw/ y escribe en data/processed/.
LIMPIEZAS = {
    "municipios": "Lista maestra de municipios (INE + coordenadas de Wikidata)",
    "aemet_limpieza": "Clima por municipio y extremos",
    "agua": "Embalses y cuencas",
    "agua_suministro": "Suministro y coste del agua",
    "energia": "Renovables, demanda y precio de la luz por municipio",
    "aeropuertos": "Distancia a aeropuertos",
    "cobertura": "Cobertura de banda ancha",
    "cpd_existentes": "CPD existentes cerca de cada municipio",
    "espacios_protegidos": "Espacios protegidos Natura 2000",
    "poblacion": "Población por municipio (padrón)",
    "movilidad_laboral": "% de ocupados residentes que trabajan fuera del municipio (INE)",
    "proyeccion_poblacion": "Proyección de población por municipio",
    "riesgos": "Riesgo sísmico y de inundación",
    "paro": "Paro registrado por municipio",
    "socioeconomico": "Renta, paro e indicadores demográficos (usa la salida de paro)",
}


def ejecutar(nombre, descripcion):
    """Ejecuta src/<nombre>.py desde la raíz del proyecto. Devuelve True si va bien."""
    print(f"\n{'=' * 70}\n>>> {nombre}: {descripcion}\n{'=' * 70}", flush=True)
    inicio = time.time()
    entorno = {**os.environ, "PYTHONUTF8": "1"}
    proceso = subprocess.run([sys.executable, str(RAIZ / "src" / f"{nombre}.py")],
                             cwd=RAIZ, env=entorno)
    ok = proceso.returncode == 0
    print(f"<<< {nombre}: {'OK' if ok else 'ERROR'} ({time.time() - inicio:.1f} s)", flush=True)
    return ok


def main():
    parser = argparse.ArgumentParser(description="Pipeline Proyecto 3 · Viabilidad CPD")
    parser.add_argument("--descargar", action="store_true",
                        help="vuelve a descargar todos los datos de origen (AEMET, REE, SEPE, INE, Natura 2000) antes de limpiar")
    parser.add_argument("--solo", nargs="+", metavar="SCRIPT",
                        help="ejecuta solo estos scripts (ver --lista)")
    parser.add_argument("--lista", action="store_true", help="muestra los scripts y sale")
    args = parser.parse_args()

    todos = {**DESCARGAS, **LIMPIEZAS}
    if args.lista:
        for nombre, descripcion in todos.items():
            if nombre in SOLO_A_MANO:
                extra = "  (solo con --descargar)"
            elif nombre in DESCARGAS:
                extra = "  (con --descargar o si faltan sus datos)"
            else:
                extra = ""
            print(f"  {nombre:<26} {descripcion}{extra}")
        return 0

    if args.solo:
        desconocidos = [s for s in args.solo if s not in todos]
        if desconocidos:
            parser.error(f"scripts desconocidos: {', '.join(desconocidos)}. Usa --lista")
        pasos = {n: d for n, d in todos.items() if n in args.solo}
        if "movilidad_laboral" in args.solo and faltan_datos("movilidad_laboral_descarga"):
            pasos = {"movilidad_laboral_descarga": DESCARGAS["movilidad_laboral_descarga"], **pasos}
    else:
        descargas = {}
        for nombre, descripcion in DESCARGAS.items():
            if args.descargar:
                descargas[nombre] = descripcion
            elif faltan_datos(nombre) and nombre in SOLO_A_MANO:
                print(f"AVISO: faltan datos de {nombre} y no se descargan solos. Recupéralos con "
                      "'git restore --source=c276ce6 data/raw' o usa --descargar")
            elif faltan_datos(nombre):
                print(f"Faltan datos de {nombre}: se descargan antes de limpiar")
                descargas[nombre] = descripcion
        pasos = {**descargas, **LIMPIEZAS}

    # municipios.csv lo genera el paso "municipios"; sin él (ni el paso) no se puede seguir
    if not RUTA_MUNICIPIOS.exists() and "municipios" not in pasos:
        print(f"ERROR: falta la lista maestra de municipios: {RUTA_MUNICIPIOS.relative_to(RAIZ)}\n"
              "Casi todos los scripts la necesitan (codigo_ine, municipio, provincia, "
              "latitud, longitud). Genérala con: python run_pipeline.py --solo municipios")
        return 1

    inicio = time.time()
    fallidos = [nombre for nombre, descripcion in pasos.items() if not ejecutar(nombre, descripcion)]

    print(f"\n{'=' * 70}\nResumen: {len(pasos) - len(fallidos)}/{len(pasos)} scripts correctos "
          f"en {time.time() - inicio:.1f} s")
    if fallidos:
        print(f"Fallaron: {', '.join(fallidos)} (mira el error encima de cada uno)")
        return 1
    print("Resultados en data/processed/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
