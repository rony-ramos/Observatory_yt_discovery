# Proyecto Observatorio Discovery

Pipeline de descubrimiento de videos de YouTube para proyectos de observacion de educacion superior. El flujo usa `yt-dlp` para buscar en la web de YouTube sin consumir cuota de busqueda de la API, enriquece metadata de los videos candidatos y filtra por institucion, fecha y cantidad minima de comentarios.

## Instalacion

Desde la carpeta del proyecto:

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Tambien puedes usar tu Python global si ya tiene las dependencias instaladas.

## Conceptos principales

- `--max-queries`: cantidad maxima de consultas que genera el planner desde el diccionario de keywords. No es un parametro de yt-dlp ni de la API.
- `--results-per-query`: cantidad maxima de resultados que yt-dlp trae por cada consulta.
- Volumen raw aproximado: `max_queries * results_per_query`.
- `--all-indicators`: genera consultas para todos los indicadores del diccionario activo.
- `--indicator`: limita la busqueda a uno o mas indicadores especificos.
- `--min-comments`: minimo de comentarios requerido para aceptar un video. Default: `75`.
- `--metadata-workers`: cantidad de validaciones de metadata en paralelo. Default conservador: `1`.

## Uso rapido

Planificar sin conectarse a YouTube:

```bat
python -m discovery --institution-id unr --require-national --all-indicators --max-queries 72 --dry-run
```

Corrida razonable para una universidad:

```bat
python -m discovery --institution-id unr --require-national --all-indicators --max-queries 72 --results-per-query 15 --min-comments 75 --metadata-workers 2
```

Corrida amplia:

```bat
python -m discovery --institution-id unr --require-national --all-indicators --max-queries 128 --results-per-query 40 --min-comments 75 --metadata-workers 2 --metadata-min-sleep 1.5 --metadata-max-sleep 3.5
```

Si aparecen errores `HTTP 429` o bloqueos temporales, bajar a `--metadata-workers 1` y subir pausas.

## YouTube API para comentarios

El pipeline no usa la API de YouTube para buscar videos. Solo puede usarla despues, de forma opcional, para completar `comment_count` cuando yt-dlp no lo obtiene.

En CMD:

```bat
set YOUTUBE_API_KEY=TU_API_KEY
python -m discovery --institution-id unr --require-national --all-indicators --max-queries 72 --results-per-query 15 --min-comments 75 --metadata-workers 2
```

En PowerShell:

```powershell
$env:YOUTUBE_API_KEY="TU_API_KEY"
python -m discovery --institution-id unr --require-national --all-indicators --max-queries 72 --results-per-query 15 --min-comments 75 --metadata-workers 2
```

Tambien puedes pasar la key directamente:

```bat
python -m discovery --institution-id unr --require-national --all-indicators --youtube-api-key TU_API_KEY
```

Si no hay API key y un video queda con `comment_count` desconocido, se rechaza como `comment_count_unknown`.

## Indicadores

El diccionario activo incluye:

- `ingreso`
- `dinero`
- `programas`
- `calidad`
- `vida_campus`
- `experiencia`

Buscar un solo indicador:

```bat
python -m discovery --institution-id unr --require-national --indicator ingreso
```

Buscar varios indicadores:

```bat
python -m discovery --institution-id unr --require-national --indicator ingreso --indicator dinero --indicator calidad
```

Buscar todos:

```bat
python -m discovery --institution-id unr --require-national --all-indicators
```

## Filtros actuales

- Universidad nacional: se activa con `--require-national`.
- Elegibilidad QS/licenciamiento: se activa con `--require-eligible`.
- Fecha: por defecto prioriza videos posteriores a `2021-12-31`.
- Institucion: por defecto `--institution-policy strict`, descarta videos que no mencionan la institucion o alias en metadata.
- Comentarios: por defecto `--min-comments 75`, descarta videos con menos comentarios o conteo desconocido.

Para excluir estrictamente videos antiguos:

```bat
python -m discovery --institution-id unr --require-national --all-indicators --date-policy strict
```

## Archivos de salida

Cada corrida crea una carpeta en `runs/`:

```text
runs/YYYYMMDD_HHMMSS_institucion_indicadores/
```

Archivos principales:

- `run.json`: manifiesto de la corrida, parametros, contadores y errores.
- `queries.csv`: consultas generadas desde el diccionario.
- `results_raw.jsonl`: resultados crudos de busqueda plana. Se escribe antes de metadata/API/filtros.
- `videos.csv`: videos aceptados despues de filtros.
- `rejected.csv`: videos descartados y razon de rechazo.

Importante: `results_raw.jsonl` puede tener `comment_count` nulo aunque la API key este configurada, porque ese archivo se escribe antes de completar metadata. Para revisar resultados finales usa `videos.csv` y `rejected.csv`.

## Columnas utiles del reporte

En `videos.csv` y `rejected.csv`:

- `video_id`, `url`, `title`, `channel`, `channel_id`
- `duration`, `view_count`, `comment_count`
- `comment_count_match`: `True` si cumple `--min-comments`.
- `published_after_match`: `True` si cumple la fecha configurada.
- `institution_match`: `True` si la metadata menciona la institucion o alias.
- `channel_classification`: `official`, `third_party` o `unclassified`.
- `query_ids`: IDs de consultas que encontraron el video.
- `search_queries`: consultas exactas que encontraron el video.
- `keywords`: keywords del diccionario usadas en esas consultas.
- `indicators`, `concepts`, `term_ids`: trazabilidad al diccionario.
- `rejection_reason`: solo en `rejected.csv`.

## Cache de videos no disponibles

Los videos que fallan como no disponibles, privados o removidos se guardan en:

```text
runs/_metadata_skip_cache.json
```

En corridas siguientes, esos IDs se saltan para no repetir validaciones inutiles.

## Comandos recomendados

Prueba rapida:

```bat
python -m discovery --institution-id unr --require-national --all-indicators --max-queries 24 --results-per-query 10 --dry-run
```

Corrida equilibrada:

```bat
python -m discovery --institution-id unr --require-national --all-indicators --max-queries 72 --results-per-query 15 --min-comments 75 --metadata-workers 2
```

Corrida amplia:

```bat
python -m discovery --institution-id unr --require-national --all-indicators --max-queries 128 --results-per-query 40 --min-comments 75 --metadata-workers 2
```

