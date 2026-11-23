# Movilidad laboral entre municipios

`src/movilidad_laboral.py` genera una fila por municipio en
`data/processed/movilidad_laboral_municipios.csv`. El indicador
`porcentaje_trabaja_fuera_municipio` es la proporción de personas ocupadas residentes que
trabajan en otro municipio.

La fuente es la matriz municipio de residencia por municipio de trabajo del Censo Anual de
Población, resultados de ocupación y actividad 2021–2023. El último año publicado es 2023.
El pipeline descarga la matriz oficial automáticamente si falta el archivo local.

```powershell
python run_pipeline.py --solo movilidad_laboral
```

El porcentaje usa como denominador a las personas ocupadas residentes, no a toda la
población. Cuenta como desplazamiento salir a trabajar a otro municipio; no cuenta a quien
trabaja en su mismo municipio. La matriz solo incluye combinaciones de residencia y trabajo
con al menos cinco personas ocupadas, por lo que los flujos menores no aparecen
individualmente.
