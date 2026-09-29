# Corrección del análisis diario — 2026-09-29

La respuesta informativa estaba restringida a ANALYSIS_LIMITED y frases genéricas,
aunque hubiera actividades utilizables. El snapshot también descartaba el deporte.

La corrección conserva únicamente deportes reconocidos y describe las actividades
seleccionadas por el modelo dentro de las fechas solicitadas. Calcula ritmo para
carrera y velocidad para bicicleta a partir de distancia y duración positivas.
Identifica el proveedor y la fecha, presenta tiempos legibles y distingue estas
observaciones de una valoración fisiológica. Las referencias anteriores del mismo
deporte y proveedor permiten comparar duración, sin inferir progreso ni equiparar
recorridos. No se modifican permisos, propuestas ni prescripciones del plan.

Las respuestas sin actividades pertinentes conservan la salida informativa previa.
No se infieren deportes a partir de velocidad, potencia o pulso. Los cálculos usan
la duración registrada, que puede incluir pausas. Esta corrección no calcula zonas,
recuperación, cumplimiento de intervalos o rendimiento relativo a umbrales.

Validación: 151 tests del worker correctos, incluidos casos de dos deportes,
distancia cero, deporte desconocido, referencia histórica, datos antiguos y límite
de longitud. La regresión falló antes de implementar la corrección. Prueba adicional
con Ollama local garmin-coach:9b y datos de ejemplo: 5:02 min/km y 22,1 km/h,
sin fallback. No se enviaron mensajes ni se modificaron trabajos del backend.

Repetir desde el worktree usando el Python del entorno sync-local y
PYTHONPATH=apps/sync-local:

    python -m unittest discover -s apps/sync-local/tests
    python apps/sync-local/tests/manual_daily_analysis_smoke.py

El segundo comando requiere Ollama local y el modelo garmin-coach:9b.
