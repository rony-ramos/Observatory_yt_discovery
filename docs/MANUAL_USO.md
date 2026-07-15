# Manual de uso del pipeline Discovery

Este manual explica como usar el pipeline para descubrir videos candidatos de YouTube, filtrar por criterios de investigacion y entender el consumo de cuota cuando se usa YouTube Data API.

Licencia del repositorio: Apache-2.0. Ver `LICENSE`.

## 1. Objetivo del pipeline

El pipeline separa dos tareas que conviene no mezclar:

1. Descubrir videos candidatos.
2. Validar y filtrar esos videos antes de extraer comentarios.

La busqueda inicial no usa `search.list` de YouTube Data API. En su lugar usa `yt-dlp` en modo de extraccion plana para consultar resultados web de YouTube. Esto evita gastar cuota de busqueda y reduce el sesgo de usar solo el buscador de la API.

Despues de descubrir videos, el pipeline puede enriquecer metadata y usar la API solo para completar datos puntuales, como `comment_count` y `upload_date`, cuando yt-dlp no los obtiene.

## 2. Instalacion

Desde la raiz del proyecto:

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

En Windows CMD, activar entorno:

```bat
.venv\Scripts\activate
```

En PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

## 3. Flujo general

El flujo completo es:

1. Cargar institucion desde el padron (`config/institutions`).
2. Cargar diccionario de keywords (`config/keywords`).
3. Generar consultas con `--indicator` o `--all-indicators`.
4. Buscar videos con yt-dlp.
5. Deduplicar por `video_id`.
6. Enriquecer metadata faltante.
7. Completar `comment_count` y `upload_date` con YouTube API si hay API key.
8. Filtrar por institucion, fecha y comentarios.
9. Guardar reportes en `runs/`.

## 4. Comando base

Ejemplo para una universidad registrada:

```bat
python -m discovery --institution-id uanl --require-eligible --all-indicators --max-queries 72 --results-per-query 15 --min-comments 75 --metadata-workers 2
```

Ejemplo para Universidad Nacional de Rosario:

```bat
python -m discovery --institution-id unr --require-national --all-indicators --max-queries 72 --results-per-query 15 --min-comments 75 --metadata-workers 2
```

## 5. Parametros principales

### `--institution-id`

ID de una universidad registrada en el padron.

Ejemplos:

```bat
--institution-id unr
--institution-id uanl
```

### `--require-national`

Exige que la institucion este marcada como universidad nacional en el padron.

Usar para universidades como:

```bat
python -m discovery --institution-id unr --require-national --indicator ingreso
```

No usar para instituciones publicas/autonomas que no sean estrictamente nacionales, como UANL.

### `--require-eligible`

Exige `licensed=true` y `qs_ranked=true` en el padron.

Ejemplo:

```bat
python -m discovery --institution-id uanl --require-eligible --all-indicators
```

### `--indicator`

Busca con un indicador especifico. Puede repetirse.

```bat
python -m discovery --institution-id unr --require-national --indicator ingreso
python -m discovery --institution-id unr --require-national --indicator ingreso --indicator dinero
```

### `--all-indicators`

Busca con todos los indicadores del diccionario activo:

- `ingreso`
- `dinero`
- `programas`
- `calidad`
- `vida_campus`
- `experiencia`

```bat
python -m discovery --institution-id unr --require-national --all-indicators
```

### `--max-queries`

Cantidad maxima de consultas generadas por el planner interno.

No es un parametro de yt-dlp ni de la API.

Ejemplo:

```bat
--max-queries 72
```

Con `--all-indicators`, este limite se reparte entre indicadores y conceptos.

### `--results-per-query`

Cantidad maxima de resultados que yt-dlp trae por cada consulta.

Ejemplo:

```bat
--results-per-query 15
```

Volumen raw aproximado:

```text
max_queries * results_per_query
```

Ejemplo:

```text
72 * 15 = hasta 1080 resultados raw
128 * 40 = hasta 5120 resultados raw
```

Despues se deduplica por `video_id`.

### `--min-comments`

Minimo de comentarios requerido para aceptar un video.

Default:

```text
75
```

Ejemplo:

```bat
--min-comments 75
```

Si un video tiene menos comentarios, se rechaza como:

```text
comment_count_below_minimum
```

Si no se puede conocer el conteo de comentarios, se rechaza como:

```text
comment_count_unknown
```

### `--metadata-workers`

Cantidad de validaciones de metadata en paralelo.

Default:

```text
1
```

Recomendado:

```bat
--metadata-workers 2
```

Si aparecen errores `HTTP 429`, bajar a:

```bat
--metadata-workers 1
```

### `--metadata-min-sleep` y `--metadata-max-sleep`

Pausa aleatoria entre validaciones de metadata.

Ejemplo para corrida amplia:

```bat
--metadata-min-sleep 1.5 --metadata-max-sleep 3.5
```

Si hay bloqueos, aumentar pausas.

## 6. Recomendaciones de escala

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
python -m discovery --institution-id unr --require-national --all-indicators --max-queries 128 --results-per-query 40 --min-comments 75 --metadata-workers 2 --metadata-min-sleep 1.5 --metadata-max-sleep 3.5
```

Para UANL:

```bat
python -m discovery --institution-id uanl --require-eligible --all-indicators --max-queries 128 --results-per-query 40 --min-comments 75 --metadata-workers 2 --metadata-min-sleep 1.5 --metadata-max-sleep 3.5
```

## 7. Uso de YouTube API

El pipeline puede usar YouTube Data API solo para completar `comment_count` y `upload_date` faltantes. No usa la API para buscar videos.

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

Tambien se puede pasar como parametro:

```bat
python -m discovery --institution-id unr --require-national --all-indicators --youtube-api-key TU_API_KEY
```

## 8. Cuotas de YouTube API

Segun la documentacion oficial de YouTube Data API:

- La cuota diaria por defecto para endpoints generales es de 10,000 unidades por dia.
- `videos.list` cuesta 1 unidad por llamada.
- `commentThreads.list` cuesta 1 unidad por llamada.
- Cada llamada invalida tambien consume al menos 1 unidad.
- Las cuotas diarias se reinician a medianoche Pacific Time (PT).

Fuentes:

- https://developers.google.com/youtube/v3/determine_quota_cost
- https://developers.google.com/youtube/v3/docs/commentThreads/list

## 9. Cuantos videos se pueden validar por dia

Validar cantidad de comentarios y fecha de publicacion no descarga comentarios. Solo consulta metadata del video con:

```text
videos.list(part=snippet,statistics)
```

Cada llamada cuesta 1 unidad y puede consultar hasta 50 IDs de video.

Con 10,000 unidades diarias:

```text
10,000 llamadas * 50 videos = hasta 500,000 videos/dia
```

Este es un limite teorico. En la practica puede ser menor por errores, reintentos, otras llamadas del proyecto o limites administrativos de la cuenta.

## 10. Cuantos videos pueden tener comentarios extraidos por dia

Extraer comentarios reales usa:

```text
commentThreads.list(videoId=...)
```

Cada llamada cuesta 1 unidad. Cada pagina puede traer hasta 100 comentarios principales.

Con 10,000 unidades diarias:

```text
10,000 paginas * 100 comentarios = hasta 1,000,000 comentarios top-level/dia
```

Estimacion por video:

```text
75 a 100 comentarios/video   -> ~1 llamada por video
300 comentarios/video        -> ~3 llamadas por video
1,000 comentarios/video      -> ~10 llamadas por video
```

Entonces, si se extraen videos con 75 a 100 comentarios:

```text
hasta ~10,000 videos/dia teoricos
```

Si cada video tiene mas comentarios, el numero de videos diarios baja proporcionalmente.

## 11. Diferencia frente al modo API-first

Modo API-first:

- Usa `search.list` para descubrir videos.
- La busqueda queda limitada por cuota de busqueda.
- Es facil agotar el cupo al combinar universidades, indicadores y keywords.

Modo de este pipeline:

- Usa yt-dlp para descubrir videos por busqueda web.
- No gasta cuota de API en descubrimiento.
- Deduplica resultados antes de usar API.
- Usa API solo para completar informacion puntual o para extraer comentarios.

Ventaja operativa:

```text
La cuota se reserva para videos ya descubiertos y filtrables, no para explorar combinaciones de keywords.
```

## 12. Archivos de salida

Cada corrida crea una carpeta en:

```text
runs/YYYYMMDD_HHMMSS_institucion_indicadores/
```

Archivos:

- `run.json`: parametros, estado, contadores y errores.
- `queries.csv`: consultas generadas desde el diccionario.
- `results_raw.jsonl`: resultados crudos de busqueda.
- `videos.csv`: videos aceptados.
- `rejected.csv`: videos rechazados y razon.

Nota importante:

```text
results_raw.jsonl se escribe antes de metadata, API y filtros.
```

Por eso puede tener:

```json
"comment_count": null
"upload_date": null
```

aunque la API key este configurada. Para revisar el resultado final, usar:

```text
videos.csv
rejected.csv
```

## 13. Columnas importantes del reporte

En `videos.csv` y `rejected.csv`:

- `video_id`: ID del video.
- `url`: URL de YouTube.
- `title`: titulo.
- `channel`: canal.
- `channel_id`: ID del canal.
- `duration`: duracion en segundos.
- `view_count`: vistas.
- `comment_count`: cantidad de comentarios.
- `comment_count_match`: `True` si cumple el minimo.
- `upload_date`: fecha de publicacion si se pudo obtener.
- `published_after_match`: `True` si cumple fecha.
- `institution_match`: `True` si menciona institucion o alias.
- `matched_aliases`: alias que hicieron match.
- `channel_classification`: `official`, `third_party` o `unclassified`.
- `query_ids`: IDs de consultas que encontraron el video.
- `search_queries`: consultas exactas que encontraron el video.
- `keywords`: keywords usadas.
- `indicators`: indicadores asociados.
- `concepts`: conceptos asociados.
- `term_ids`: terminos del diccionario.
- `rejection_reason`: razon de descarte, solo en `rejected.csv`.

## 14. Razones comunes de rechazo

```text
institution_not_found_in_metadata
metadata_unavailable
comment_count_below_minimum
comment_count_unknown
published_on_or_before_cutoff
```

## 15. Cache de videos no disponibles

El pipeline guarda IDs de videos no disponibles, privados o removidos en:

```text
runs/_metadata_skip_cache.json
```

En siguientes corridas, esos IDs se saltan para no repetir validaciones inutiles.

## 16. Buenas practicas

- Primero ejecutar con `--dry-run`.
- Para todos los indicadores, usar al menos `--max-queries 72`.
- Para corrida amplia, usar `--max-queries 128 --results-per-query 40`.
- Usar `--metadata-workers 2` como punto de partida.
- Si hay bloqueos, bajar workers y subir pausas.
- Revisar `videos.csv` y `rejected.csv`, no solo `results_raw.jsonl`.
- Mantener `--min-comments 75` para asegurar densidad conversacional.
- Usar `--require-national` solo cuando la universidad sea nacional en sentido institucional.
- Usar `--require-eligible` cuando se quiera exigir QS/licenciamiento del padron.
