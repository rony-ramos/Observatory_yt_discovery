# Proyecto Observatorio Discovery

Pipeline de descubrimiento de videos de YouTube para proyectos de observacion de educacion superior. El flujo usa `yt-dlp` para buscar en la web de YouTube sin consumir cuota de busqueda de la API, enriquece metadata de los videos candidatos y filtra por institucion, fecha y cantidad minima de comentarios.

Manual completo: [docs/MANUAL_USO.md](docs/MANUAL_USO.md)

Licencia: Apache-2.0. Ver [LICENSE](LICENSE).

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

El pipeline no usa la API de YouTube para buscar videos. Solo puede usarla despues, de forma opcional, para completar `comment_count` y `upload_date` cuando yt-dlp no los obtiene.

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

Si no hay API key y un video queda con `comment_count` desconocido, se rechaza como `comment_count_unknown`. Si falta `upload_date`, el filtro de fecha queda como desconocido salvo que yt-dlp o la API lo completen.

### Descargar comentarios desde un Excel

El descargador puede leer el mismo XLSX usado para descargar videos y generar un
CSV independiente por video. En CMD:

```bat
set YOUTUBE_API_KEY=TU_API_KEY
python -m discovery.download --input "A:\USIL CS\GICC USIL\observatory_ws\repository\Proyecto-Observatorio-Discovery\uploads\upload_1.xlsx" --download-comments --workers 2
```

Este modo usa YouTube Data API y no necesita cookies. Descarga por defecto los
comentarios principales y todas sus respuestas. Para excluir respuestas usa
`--exclude-replies`; para limitar el volumen usa, por ejemplo,
`--max-comments-per-video 500`.

Los archivos quedan organizados de esta forma:

```text
downloads/<universidad>/comments/<video_id>_comments.csv
```

Cada fila incluye el titulo, canal y fecha del video, institucion, texto del
comentario, autor, fecha de publicacion y actualizacion, cantidad de likes,
identificador del comentario y relacion con su comentario padre. Ademas, cada
ejecucion genera automaticamente el consolidado simple
`downloads/_reports/<corrida>/comentarios.xlsx` con las columnas `Fecha`,
`Video`, `Titulo`, `Universidad`, `Comentario` y `Likes`.

## Indicadores

El pipeline carga por defecto el diccionario `natural` v1.1.0 mediante
`config/keywords/manifest.yaml`. Sus consultas usan frases completas y de alta
intencion. La version 1.0.0 se conserva para reproducibilidad experimental.

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
- Pais de la fuente: por defecto `--source-country-policy strict`, acepta solo canales asociados al mismo pais de la universidad y rechaza pais desconocido.
- Comentarios: por defecto `--min-comments 75`, descarta videos con menos comentarios o conteo desconocido.

El pais de la fuente se obtiene de `channel.snippet.country` mediante YouTube Data
API. Es un dato declarado por el canal y no una prueba legal de nacionalidad. Los
canales oficiales verificados de la universidad se consideran evidencia local. En
modo `strict` se requiere `YOUTUBE_API_KEY` para validar canales de terceros.

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

Importante: `results_raw.jsonl` puede tener `comment_count` o `upload_date` nulos aunque la API key este configurada, porque ese archivo se escribe antes de completar metadata. Para revisar resultados finales usa `videos.csv` y `rejected.csv`.

## Columnas utiles del reporte

En `videos.csv` y `rejected.csv`:

- `video_id`, `url`, `title`, `channel`, `channel_id`
- `duration`, `view_count`, `comment_count`
- `comment_count_match`: `True` si cumple `--min-comments`.
- `published_after_match`: `True` si cumple la fecha configurada.
- `institution_match`: `True` si la metadata menciona la institucion o alias.
- `channel_classification`: `official`, `third_party` o `unclassified`.
- `channel_country`: codigo de pais declarado por el canal.
- `source_country_match`: `True` solo cuando coincide con el pais de la universidad.
- `source_country_evidence`: `channel_metadata`, `official_channel_registry` o `unknown`.
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

## Experimentos de diccionario

La suite `config/experiments/keyword-dictionary-1.0.0.yaml` compara cinco perfiles
sin cambiar el diccionario activo:

- `baseline` (`1.0.0`): diccionario historico original.
- `natural` (`1.1.0`): frases naturales y de alta intencion.
- `regional` (`1.2.0`): vocabulario administrativo y estudiantil local.
- `local_context` (`1.3.0`): combina lenguaje natural y vocabulario regional.
- `combined` (`1.4.0`): integra las estrategias y combinaciones curadas.

Validar la suite:

```bat
python scripts\validate_experiment.py
```

Generar los cinco planes para la UNR sin conectarse a YouTube:

```bat
python -m discovery.experiment --institution-id unr --require-national
```

Ejecutar la comparacion controlada. Cada version usa 84 consultas y 15 resultados
por consulta:

```bat
set YOUTUBE_API_KEY=TU_API_KEY
python -m discovery.experiment --institution-id unr --require-national --execute --source-country-policy strict --metadata-workers 2
```

Probar solamente la version combinada con 128 consultas, tres variantes por termino
y mas consultas combinadas:

```bat
python -m discovery.experiment --institution-id unr --require-national --scenario expanded --profile combined --execute --metadata-workers 2
```

Sustituye `combined` por el perfil que gane la comparacion controlada.

Para planificar o ejecutar un solo perfil del escenario controlado:

```bat
python -m discovery.experiment --institution-id unr --require-national --profile regional
```

Cada experimento se guarda en `experiments/` e incluye:

- `experiment.json`: configuracion y corridas realizadas.
- `summary.csv`: comparacion de volumen, precision institucional, comentarios y seleccion.
- Una carpeta por perfil con `queries.csv`, `run.json` y las salidas normales.
- `video_comparison.csv`: solapamiento de videos entre perfiles al ejecutar busquedas.
- `review_candidates.csv`: videos seleccionados con columnas para validacion manual.

Las consultas combinadas quedan identificadas mediante `query_kind`,
`combination_id` y `combines`. Son combinaciones declaradas en la suite, no una
mezcla automatica de todas las keywords.
