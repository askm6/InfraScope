"""Descarga (o vuelve a descargar) los datos de origen de espacios_protegidos.py en
data/raw/medioambiente/:
  - la capa de la Red Natura 2000 del MITECO en GML (unos 200 MB),
  - el mapa de tierra emergida de Natural Earth (unos 10 MB).

espacios_protegidos.py ya los descarga si faltan; este script sirve para actualizarlos
(python run_pipeline.py --descargar o --solo natura2000_descarga).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from espacios_protegidos import RUTA_NATURA, RUTA_TIERRA, URL_NATURA, URL_TIERRA, descargar  # noqa: E402

if __name__ == "__main__":
    for url, ruta in [(URL_NATURA, RUTA_NATURA), (URL_TIERRA, RUTA_TIERRA)]:
        descargar(url, ruta, forzar=True)
        print(f"Guardado {ruta} ({ruta.stat().st_size / 1e6:.0f} MB)")
