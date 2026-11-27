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
  raw/                        capa Bronze: datos de origen, una carpeta por fuente
  processed/                  zona de trabajo: CSV que dejan los scripts de limpieza
  silver/                     capa Silver: los datos limpios en Parquet, tipados y validados
  gold/                       capa Gold: tablas finales para modelos y dashboard (Parquet)
docs/                         informes y manuales (ver docs/data_lake.md)
src/
  *_descarga.py               descargan datos de una API a data/raw/
                              (aemet, ree_precios, ree_ccaa_mensual, datadis)
  aemet_limpieza.py, agua.py, energia.py, cobertura.py, ...
                              un script de limpieza por fuente: lee data/raw/
                              y escribe en data/processed/
  municipios_limites.py       superficie de cada municipio con los límites oficiales del IGN
  etl.py                      junta los datasets limpios en una tabla única por municipio
                              (tabla_integrada.csv, que acaba en la capa Gold)
  convertir_parquet.py        pasa los CSV de data/processed/ a Parquet (Silver y Gold)
  lago.py                     capas del Data Lake y leer("dataset") para cargar un Parquet
  territorio.py               códigos INE de provincias y comunidades
  movilidad_laboral.py        porcentaje de ocupados que trabaja fuera del municipio,
                              ver docs/movilidad_laboral.md
  warehouse.py, modelos.py, simulador.py, dashboard.py
                              pendientes (todavía vacíos, ver las issues)
tests/                        tests automáticos (python -m pytest)
comprobar_datos.py            comprueba que los datos generados están completos y cuadran
run_pipeline.py               ejecuta descargas, limpiezas, la tabla única y el paso a Parquet
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
datos de `data/raw/` y guarda el resultado en `data/processed/`. Después, `etl` junta lo
principal en una tabla única por municipio (`tabla_integrada.csv`) y el último paso,
`convertir_parquet`, lo pasa todo a Parquet en `data/silver/` y `data/gold/` (ver
[docs/data_lake.md](docs/data_lake.md)). Al final aparece un resumen con los scripts que han
ido bien y los que han fallado.

Para comprobar que los datos generados están completos y cuadran con cifras oficiales
(población, paro, superficie de España):

```powershell
python comprobar_datos.py
```

Otras opciones:

| Orden | Qué hace |
|---|---|
| `python run_pipeline.py --lista` | Muestra todos los scripts que se pueden ejecutar |
| `python run_pipeline.py --solo agua energia` | Ejecuta solo los scripts indicados |
| `python run_pipeline.py --descargar` | Vuelve a descargar los datos de AEMET y REE y después limpia todo |
| `python run_pipeline.py --solo convertir_parquet` | Solo pasa a Parquet los CSV que han cambiado |

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

### 4. Leer los datos en Parquet

Los modelos, los notebooks y el cuadro de mandos leen los datos de Silver y Gold, no los CSV:

```python
from src.lago import leer

paro = leer("paro_municipios")                                     # tabla completa
energia = leer("energia_municipios", ["codigo_ine", "renovable_pct"])  # solo esas columnas
```

En Parquet, `codigo_ine` ya es texto de 5 cifras (`01001`) y los años son números enteros.
Qué columnas, tipos y huecos tiene cada dataset está en `data/silver/catalogo.json`.
Por qué Parquet, qué es cada capa (Bronze, Silver, Gold) y cómo se valida cada tabla:
[docs/data_lake.md](docs/data_lake.md).

Tests: `python -m pytest`

### 5. Cuadro de mandos (pendiente)

`src/dashboard.py` todavía está vacío. Cuando esté hecho se abrirá con:

```powershell
streamlit run src/dashboard.py
```

## Cómo trabajamos (issues, ramas y pull requests)

Todo el trabajo se organiza en GitHub, en
[issues](https://github.com/askm6/InfraScope/issues) agrupadas en 4 fases (milestones):
Fase 1 · Datos, Fase 2 · Frontend, Fase 3 · Modelos y Fase 4 · Entrega. Cada issue lleva una
etiqueta (`datos`, `frontend`, `modelos`, `documentation`, `testing`) y una persona asignada.

Nadie trabaja directamente en `main`. Para cada issue:

1. **Crear la rama desde la issue** (botón *Create a branch* de la issue o con `gh`). La rama
   se llama como la issue, por ejemplo `35-pasar-los-datasets-a-parquet`:

   ```powershell
   git checkout main
   git pull
   gh issue develop 35 --checkout
   ```

2. **Trabajar y guardar los cambios** con commits pequeños que expliquen qué se ha hecho:

   ```powershell
   git add src/mi_script.py tests/test_mi_script.py
   git commit -m "feat: descripción corta de lo que se ha hecho"
   git push -u origin 35-pasar-los-datasets-a-parquet
   ```

   Antes de subir, ejecuta los tests: `python -m pytest`.

3. **Abrir una pull request (PR) a `main`** que explique qué hace, por qué y cómo probarlo.
   Escribe `Closes #35` en la descripción para que la issue se cierre sola al hacer merge.

4. **Revisión:** otra persona del equipo revisa la PR y deja comentarios si hace falta.

5. **Subir a `main` (merge):** cuando la PR está revisada, se hace *Merge pull request* en
   GitHub (o `gh pr merge <número de la PR> --merge --delete-branch`; ojo, el número de la
   PR no es el de la issue). Los cambios pasan a `main`, la rama se borra y la issue se cierra.

6. **Actualizar tu copia local** para empezar la siguiente issue desde lo último:

   ```powershell
   git checkout main
   git pull
   ```

La primera vez en un ordenador nuevo, configura tu nombre para los commits. Usa el correo
privado que da GitHub (*Settings → Emails*) si no quieres que se vea el tuyo:

```powershell
git config --global user.name "Tu Nombre"
git config --global user.email "ID+usuario@users.noreply.github.com"
```
