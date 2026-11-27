"""Capas del Data Lake del proyecto y cómo leer sus datos.

  - Bronze (data/raw/):    datos de origen tal como llegan de cada fuente. No se tocan.
  - data/processed/:       zona de trabajo. Los scripts de limpieza dejan aquí sus CSV.
  - Silver (data/silver/): los CSV limpios pasados a Parquet, con tipos correctos y validados.
  - Gold (data/gold/):     tablas listas para el análisis, los modelos y el cuadro de mandos.

Uso desde cualquier script, notebook o desde el dashboard:
    from src.lago import leer
    energia = leer("energia_municipios")                                   # tabla completa
    energia = leer("energia_municipios", ["codigo_ine", "renovable_pct"])  # solo esas columnas
"""
import json
import warnings
from enum import Enum
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]
DIR_DATOS = RAIZ / "data"          # los tests lo cambian por una carpeta temporal

# Marca que pone convertir_parquet.py en el catálogo cuando el último CSV no se pudo
# convertir y el Parquet que queda es el de la vez anterior
MARCA_DESACTUALIZADO = "desactualizado"


class Capa(Enum):
    """Capas del Data Lake (arquitectura medallón Bronze / Silver / Gold)."""
    BRONZE = "raw"
    SILVER = "silver"
    GOLD = "gold"

    @property
    def carpeta(self) -> Path:
        return DIR_DATOS / self.value

    @property
    def catalogo(self) -> Path:
        """JSON con la descripción de cada dataset de la capa (filas, tipos, origen...)."""
        return self.carpeta / "catalogo.json"


ORDEN_PARA_LEER = (Capa.GOLD, Capa.SILVER)


def carpeta_trabajo() -> Path:
    """Carpeta donde los scripts de limpieza escriben sus CSV (data/processed/)."""
    return DIR_DATOS / "processed"


def ruta(nombre: str, capa: Capa) -> Path:
    """Ruta del Parquet de un dataset en una capa: data/<capa>/<nombre>.parquet."""
    return capa.carpeta / f"{nombre}.parquet"


def entrada_catalogo(nombre: str, capa: Capa) -> dict:
    """Lo que dice el catálogo de la capa sobre un dataset ({} si no hay catálogo)."""
    try:
        return json.loads(capa.catalogo.read_text(encoding="utf-8")).get(nombre, {})
    except (OSError, json.JSONDecodeError):
        return {}


def leer(nombre: str, columnas: list[str] | None = None) -> pd.DataFrame:
    """Lee un dataset en Parquet. Lo busca primero en Gold y después en Silver.

    Con `columnas` solo se cargan esas columnas: Parquet guarda los datos por columnas,
    así que no hace falta leer el archivo entero. Si la última conversión de ese dataset
    falló, avisa de que los datos son los de la vez anterior.
    """
    for capa in ORDEN_PARA_LEER:
        archivo = ruta(nombre, capa)
        if archivo.exists():
            if entrada_catalogo(nombre, capa).get(MARCA_DESACTUALIZADO):
                warnings.warn(f"'{nombre}' está desactualizado: la última conversión falló y "
                              "se usan los datos de la vez anterior", UserWarning, stacklevel=2)
            return pd.read_parquet(archivo, columns=columnas)
    raise FileNotFoundError(
        f"No existe '{nombre}.parquet' en data/gold/ ni en data/silver/. "
        "Genéralo con: python run_pipeline.py --solo convertir_parquet")


def disponibles() -> dict[str, list[str]]:
    """Datasets en Parquet de cada capa: {'silver': [...], 'gold': [...]}."""
    return {capa.value: sorted(p.stem for p in capa.carpeta.glob("*.parquet"))
            for capa in (Capa.SILVER, Capa.GOLD)}
