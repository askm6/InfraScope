# Proyecto 3 · Sistema de Predicción de Viabilidad de un CPD

Plataforma en Python que puntúa (0–100) la viabilidad de instalar un Centro de
Procesamiento de Datos en cada municipio español y proyecta su sostenibilidad a 10 años.
Usa datos públicos reales: AEMET, REE, Datadis, INE, MITMA, SEPE, PeeringDB, OpenStreetMap,
MITECO (Red Natura 2000), Natural Earth, entre otros.

## Estructura

```
config/
  config.yaml                 parámetros del proyecto (CPD de referencia, etc.)
data/                         no se sube a GitHub (ver "Conseguir los datos")
  raw/                        datos de origen, una carpeta por fuente
  processed/                  datos limpios por municipio, listos para el modelo
docs/                         informes y manuales
src/
  *_descarga.py               descargan datos de una API a data/raw/
                              (aemet, ree_precios, ree_ccaa_mensual, datadis)
  aemet_limpieza.py, agua.py, energia.py, cobertura.py, ...
                              un script de limpieza por fuente: lee data/raw/
                              y escribe en data/processed/
  territorio.py               códigos INE de provincias y comunidades
  movilidad_laboral.py        porcentaje de ocupados que trabaja fuera del municipio,
                              ver docs/movilidad_laboral.md
  etl.py, warehouse.py, modelos.py, simulador.py, dashboard.py
                              pendientes (todavía vacíos)
run_pipeline.py               ejecuta descargas y limpiezas con una sola orden
```

## Uso

### 1. Preparar el entorno (solo la primera vez)

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Conseguir los datos (solo la primera vez)

Los datasets no se suben a GitHub: todo lo que hay dentro de `data/` está en el
`.gitignore`. Por eso, al clonar el repositorio, `data/raw/` y `data/processed/` están vacías.

1. Recupera los datos de origen del historial de Git. El commit `c276ce6` es el último que
   los tenía:

   ```powershell
   git restore --source=c276ce6 data/raw
   ```

   Los archivos se guardan en tu ordenador, pero Git los sigue ignorando y no se vuelven a
   subir. También sirve si al hacer `git pull` se te han borrado los datos.

2. Copia `municipios.csv`, la lista maestra de municipios (`codigo_ine, municipio, provincia,
   latitud, longitud`), en `data/processed/`. No está en el repositorio y ningún script la
   genera, así que pídesela a alguien del equipo. Sin ella el proceso no arranca.

### 3. Ejecutar todo el proceso con una sola orden

Desde la raíz del proyecto:

```powershell
python run_pipeline.py
```

Ejecuta, uno detrás de otro, todos los scripts de limpieza de `src/`. Cada uno lee sus
datos de `data/raw/` y guarda el resultado en `data/processed/`. Al final aparece un
resumen con los scripts que han ido bien y los que han fallado.

Otras opciones:

| Orden | Qué hace |
|---|---|
| `python run_pipeline.py --lista` | Muestra todos los scripts que se pueden ejecutar |
| `python run_pipeline.py --solo agua energia` | Ejecuta solo los scripts indicados |
| `python run_pipeline.py --descargar` | Vuelve a descargar los datos de AEMET y REE y después limpia todo |

Solo los datos de AEMET y REE tienen script de descarga. Si falta algún archivo de REE en
`data/raw/`, el proceso lo descarga antes de limpiar. Los de AEMET nunca se descargan solos
(tardan mucho): si faltan, el proceso avisa y hay que recuperarlos como en el apartado 2 o
usar `--descargar`. `espacios_protegidos` descarga por su cuenta, si no están en
`data/raw/medioambiente/`, la capa de la Red Natura 2000 del MITECO (unos 200 MB) y el
mapa de tierra de Natural Earth. Al terminar, la descarga de AEMET borra los `mensuales_*.json`
intermedios y solo deja los CSV y `estaciones.json`. El resto de datos de origen se
descargó a mano y solo se puede recuperar como se explica en el apartado 2. Usa `--descargar` si quieres
actualizar los de AEMET y REE: tarda varios minutos y la descarga de AEMET necesita la API
key en el archivo `.env` de la raíz del proyecto:

```
AEMET_API_KEY=tu_clave
```

La clave se pide gratis en <https://opendata.aemet.es/centrodedescargas/altaUsuario>. El
`.env` está en el `.gitignore`: no lo subas nunca.

#### Consumo eléctrico de Datadis

La descarga de Datadis no forma parte del pipeline porque es muy lenta (una consulta por
mes y municipio, de 10 a 30 s cada una). Se lanza a mano, y si se corta, al relanzarla
sigue donde se quedó:

```powershell
python src/datadis_descarga.py                          # desde 2022-01 hasta el mes pasado
python src/datadis_descarga.py --desde 2025-01 --hasta 2025-12
```

Después se limpia con:

```powershell
python src/consumo_electrico.py
```

#### Desplazamientos al trabajo fuera del municipio

`src/movilidad_laboral.py` calcula qué porcentaje de las personas ocupadas residentes en cada municipio trabaja en otro municipio, usando la matriz residencia-trabajo del Censo Anual del INE (2023). Consulta [documentación](docs/movilidad_laboral.md) para descargar la matriz y generar `data/processed/movilidad_laboral_municipios.csv`.
#### Si algo falla

- *Falta la lista maestra de municipios*: copia `municipios.csv` en `data/processed/`
  (apartado 2).
- *FileNotFoundError en `data/raw/...`*: faltan datos de origen. Recupéralos con el
  `git restore` del apartado 2.
- *Error en `aemet_descarga`*: revisa que el `.env` tenga la `AEMET_API_KEY` y que sea
  válida.
- Para repetir solo lo que ha fallado, usa `--solo` con los nombres que aparecen en el
  resumen final.

### 4. Cuadro de mandos (pendiente)

`src/dashboard.py` todavía está vacío. Cuando esté hecho se abrirá con:

```powershell
streamlit run src/dashboard.py
```
