"""Ejecuta con una sola orden todos los scripts de limpieza de datos.

Uso:
    python run_pipeline.py                      # descarga lo que falte de REE y limpia todo
    python run_pipeline.py --descargar          # antes vuelve a descargar todo (AEMET y REE)
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
}

# Archivos que deja cada descarga: si falta alguno, hay que descargar
ARCHIVOS_DESCARGA = {
    "aemet_descarga": ["data/raw/aemet/aemet_mensual.csv",
                       "data/raw/aemet/municipio_estacion.csv"],
    "ree_precios_descarga": ["data/raw/energia/ree_precios_horarios.csv"],
    "ree_ccaa_mensual_descarga": ["data/raw/energia/ree_demanda_ccaa_mensual.csv",
                                  "data/raw/energia/ree_generacion_renovable_ccaa_mensual.csv"],
}


# Descargas que nunca se lanzan solas (solo con --descargar o --solo): la de AEMET
# tarda mucho y llena data/raw/aemet/ de JSON intermedios
SOLO_A_MANO = {"aemet_descarga"}


def faltan_datos(nombre):
    """True si a la descarga le falta alguno de sus archivos en data/raw/."""
    return any(not (RAIZ / ruta).exists() for ruta in ARCHIVOS_DESCARGA.get(nombre, []))

# Limpieza: lee data/raw/ y escribe en data/processed/.
LIMPIEZAS = {
    "aemet_limpieza": "Clima por municipio y extremos",
    "agua": "Embalses y cuencas",
    "agua_suministro": "Suministro y coste del agua",
    "energia": "Demanda, renovables y picos de precio",
    "aeropuertos": "Distancia a aeropuertos",
    "cobertura": "Cobertura de banda ancha",
    "cpd_existentes": "CPD existentes cerca de cada municipio",
    "espacios_protegidos": "Espacios protegidos Natura 2000",
    "poblacion": "Población por provincia",
    "proyeccion_poblacion": "Proyección de población",
    "riesgos": "Riesgo sísmico y de inundación",
    "socioeconomico": "Renta, paro e indicadores demográficos",
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
                        help="vuelve a descargar todos los datos de AEMET y REE antes de limpiar")
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

    if not RUTA_MUNICIPIOS.exists():
        print(f"ERROR: falta la lista maestra de municipios: {RUTA_MUNICIPIOS.relative_to(RAIZ)}\n"
              "Casi todos los scripts la necesitan (codigo_ine, municipio, provincia, "
              "latitud, longitud).")
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
