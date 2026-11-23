"""Descarga la matriz residencia-trabajo del Censo Anual del INE."""
from pathlib import Path

import requests

RAIZ = Path(__file__).resolve().parent.parent
URL = "https://www.ine.es/metodologia/t20/matriz_ocu_anonim.xlsb"
SALIDA = RAIZ / "data" / "raw" / "trabajo" / "matriz_residencia_trabajo_2023.xlsb"


def main():
    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    temporal = SALIDA.with_suffix(SALIDA.suffix + ".part")
    respuesta = requests.get(URL, timeout=(30, 180), stream=True)
    respuesta.raise_for_status()
    with temporal.open("wb") as archivo:
        for bloque in respuesta.iter_content(chunk_size=1024 * 1024):
            if bloque:
                archivo.write(bloque)
    if temporal.stat().st_size < 100_000:
        temporal.unlink(missing_ok=True)
        raise ValueError("La descarga del INE está incompleta o no parece ser un XLSB válido")
    temporal.replace(SALIDA)
    print(f"Descargado: {SALIDA.relative_to(RAIZ)} ({SALIDA.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
