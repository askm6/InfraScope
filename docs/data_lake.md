# Data Lake: capas Bronze, Silver y Gold

Los datos del proyecto se organizan en un Data Lake con la arquitectura medallón: cada capa
tiene datos más limpios y más listos para usar que la anterior. Así siempre se puede volver
atrás y reconstruir cualquier tabla desde los datos de origen.

| Capa | Carpeta | Qué contiene | Formato |
|---|---|---|---|
| Bronze | `data/raw/` | Datos de origen tal como llegan de cada fuente (AEMET, REE, INE, MITECO…). No se modifican. | CSV, XLSX, JSON, GML… |
| (zona de trabajo) | `data/processed/` | Salida de los scripts de limpieza: un CSV por dataset. | CSV |
| Silver | `data/silver/` | Los mismos datasets limpios, con el tipo correcto en cada columna y validados. | Parquet |
| Gold | `data/gold/` | Tablas finales para el análisis, los modelos y el cuadro de mandos (por ejemplo, la tabla única por municipio, issue #34). | Parquet |

Ninguna de estas carpetas se sube a GitHub (`.gitignore`): se regeneran con `python run_pipeline.py`.

```
Fuentes (APIs, descargas) ──> Bronze: data/raw/
                                 │  scripts de limpieza (src/*.py), incluido
                                 │  src/municipios_limites.py (superficie, IGN)
                                 ▼
                              data/processed/*.csv
                                 │  src/etl.py ──> data/processed/tabla_integrada.csv
                                 │  src/convertir_parquet.py (tipar + validar)
                                 ▼
          Silver: data/silver/*.parquet          Gold: data/gold/tabla_integrada.parquet
          (un dataset limpio por fuente)          (tabla única por municipio)
                                 │                         │
                                 └──── src/lago.py: leer("dataset") ────┘
                                                   │
                              DuckDB (issue #36), modelos y dashboard
```

Todo esto lo hace `python run_pipeline.py` en orden: limpiezas → `etl` → `convertir_parquet`.
Después, `python comprobar_datos.py` revisa que todo esté completo y cuadre con cifras oficiales.

## Por qué Parquet

Parquet es un formato binario que guarda los datos **por columnas**, **comprimidos** y con el
**tipo** de cada columna:

- **Ocupa menos.** Con los datos reales, los 22 datasets pasan de 20,6 MB en CSV a 3,8 MB en
  Parquet (un 81 % menos). La tabla más grande, `espacios_protegidos_limpio`, pasa de 7,9 MB a
  0,6 MB. Los archivos muy pequeños (menos de 100 filas) ocupan un poco más en Parquet, porque
  guardan también la descripción de las columnas; aun así compensa tenerlo todo en el mismo formato.
- **Se lee más rápido.** `espacios_protegidos_limpio` (81.134 filas) tarda unos 39 ms en CSV y
  8 ms en Parquet; si solo se piden 2 columnas, 6 ms. Al ser por columnas, no hace falta leer
  el archivo entero.
- **Guarda los tipos.** En CSV todo es texto y pandas tiene que adivinar el tipo de cada
  columna, y a veces se equivoca: el código INE `01001` se leía como el número `1001`, y los
  años con huecos salían con decimales (`2024.0`). En Parquet se guardan bien una vez y ya
  no hay que corregirlos cada vez que se leen.
- **Lo leen directamente DuckDB, pandas y Spark**, que es lo que usará el Data Warehouse.

## Qué hace `src/convertir_parquet.py`

Para cada CSV de `data/processed/`:

1. **Tipar** (`tipar`):
   - `codigo_ine` → texto de 5 cifras (`01001`); `codigo_provincia` → texto de 2 cifras.
   - Años, meses, semanas, contadores (`n_*`, `num_*`, `meses*`) y personas (`poblacion*`,
     `habitantes`…) → número entero con huecos permitidos (`Int64`), solo si no tienen decimales.
   - Columnas `fecha*` → fecha, solo si todos los valores son fechas completas `AAAA-MM-DD`
     (un `2016-03` o un número se dejan como están, para no inventar el día).
2. **Validar** (`validar`):
   - La clave de la tabla no puede tener huecos ni filas repetidas. Las claves están en el diccionario
     `CLAVES` y se han comprobado sobre los datos reales (por ejemplo, `paro_municipios` tiene una
     fila por municipio y año). Las tablas `*_municipios` tienen una fila por municipio.
   - `codigo_ine` tiene que tener 5 cifras. Si algún código no está en la lista maestra
     `municipios.csv`, se avisa, pero no se bloquea.
   - Se avisa (sin bloquear) si una columna que parece un código está guardada como número
     o si un contador tiene decimales.
   - Si hay algún error, ese dataset **no se guarda** y el paso termina con error. Si existía
     un Parquet anterior, se mantiene pero queda marcado como `desactualizado` en el catálogo,
     y `leer()` lo avisa al cargarlo.
3. **Guardar** en `data/silver/<nombre>.parquet`, o en `data/gold/` si el dataset está en
   `DATASETS_GOLD`, con compresión zstd. Se escribe primero un temporal y después se renombra,
   para que nunca quede un archivo a medias.
4. **Catálogo** (`data/silver/catalogo.json` y `data/gold/catalogo.json`): de cada dataset se
   apunta el CSV de origen, las filas, las columnas, la clave, el tipo de cada columna, el % de
   huecos por columna, el tamaño en CSV y en Parquet, la fecha y la **huella sha256** del CSV.
   Sirve de diccionario de datos y para saber de dónde sale cada tabla.
5. **Carga incremental:** si la huella del CSV es la misma que la última vez, las reglas de
   tipado no han cambiado (`VERSION_ESQUEMA`) y el Parquet existe, no se vuelve a convertir
   (`sin cambios`). Con `--forzar` se convierte todo de nuevo.

Si un dataset falla (por ejemplo, el CSV está abierto en Excel o tiene la clave repetida), se
apunta el error y **se siguen convirtiendo los demás**; el catálogo se guarda igualmente. Todos
los archivos (Parquet y catálogo) se escriben primero en un temporal, así que un corte a
mitad nunca deja un archivo roto. Si el catálogo se estropea, se vuelve a crear desde cero.
También se avisa de los Parquet que ya no tienen CSV en `data/processed/`.

Si se cambian las reglas de tipado o de validación, hay que subir `VERSION_ESQUEMA` en
`src/convertir_parquet.py` para que todo se vuelva a convertir con las reglas nuevas.

Se comprobó, columna a columna, que los 22 Parquet tienen exactamente los mismos valores y
huecos que sus CSV.

## Cómo usarlo

```powershell
python run_pipeline.py                              # limpia todo y al final pasa a Parquet
python run_pipeline.py --solo convertir_parquet     # solo la conversión
python src/convertir_parquet.py --forzar            # vuelve a convertir aunque no haya cambios
python src/convertir_parquet.py --solo paro_municipios energia_municipios
```

Para leer los datos desde cualquier script, notebook o el dashboard:

```python
from src.lago import leer, disponibles

disponibles()                     # {'silver': ['aeropuertos', ...], 'gold': [...]}
paro = leer("paro_municipios")    # busca primero en Gold y después en Silver
energia = leer("energia_municipios", ["codigo_ine", "renovable_pct", "precio_medio_eur_mwh"])
```

## Para añadir un dataset nuevo

1. El script de limpieza deja su CSV en `data/processed/`. No hace falta nada más: el paso de
   Parquet lo convierte solo.
2. Si no tiene una fila por municipio, añade su clave a `CLAVES` en `src/convertir_parquet.py`.
3. Si es una tabla final para el dashboard o los modelos, añade su nombre a `DATASETS_GOLD`.
