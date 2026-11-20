# Proyecto 3 · Sistema de Predicción de Viabilidad de un CPD

Plataforma en Python que puntúa (0–100) la viabilidad de instalar un Centro de
Procesamiento de Datos en cada municipio español y proyecta su sostenibilidad a 10 años.
Los datos son sintéticos y reproducibles.

## Estructura

```
config/
  config.yaml       parámetros del proyecto
data/
  raw/              datos de origen (generados)
  processed/        datos limpios e integrados
docs/               informes y manuales
src/
  catalogo.py       provincias y referencias territoriales
  generar_datos.py  genera las fuentes sintéticas
  etl.py            limpieza e integración
  warehouse.py      Data Warehouse (DuckDB)
  modelos.py        score, Machine Learning y series temporales
  simulador.py      simulador de escenarios
  dashboard.py      cuadro de mandos (Streamlit)
  utils.py          configuración y rutas
run_pipeline.py     ejecuta todo el proceso
```

## Uso

### 1. Preparar el entorno (solo la primera vez)

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Ejecutar todo el proceso con una sola orden

Desde la raíz del proyecto:

```powershell
python run_pipeline.py
```

Ejecuta, uno detrás de otro, todos los scripts de limpieza de `src/`. Cada uno lee sus
datos de `data/raw/` y guarda el resultado en `data/processed/`. Al final aparece un
resumen con los scripts que han ido bien y los que han fallado.

Antes de ejecutarlo tiene que existir `data/processed/municipios.csv`, la lista maestra de
municipios (`codigo_ine, municipio, provincia, latitud, longitud`).

Otras opciones:

| Orden | Qué hace |
|---|---|
| `python run_pipeline.py --lista` | Muestra todos los scripts que se pueden ejecutar |
| `python run_pipeline.py --solo agua energia` | Ejecuta solo los scripts indicados |
| `python run_pipeline.py --descargar` | Vuelve a descargar los datos de AEMET y REE y después limpia todo |

Por defecto no se descarga nada, porque los datos de origen ya están en `data/raw/`. Usa
`--descargar` solo si quieres actualizarlos: tarda varios minutos y la descarga de AEMET
necesita la API key en el archivo `.env` (`AEMET_API_KEY=tu_clave`).

### 3. Cuadro de mandos

```powershell
streamlit run src/dashboard.py
```
