# Fase 3, entregable 4 — Experimento mínimo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Obtener una comparación ciega reproducible entre Ollama y el selector determinista, sin integrar generación en producción.

**Architecture:** Un arnés local materializa los fixtures congelados y construye los mismos snapshots y catálogos para ambos selectores. Ollama devuelve exclusivamente selecciones tipadas; ambos caminos usan `validate_selection` y `render_selection`. Los resultados técnicos y la clave de anonimización se separan del paquete de revisión.

**Tech Stack:** Python, unittest, httpx ya utilizado por el worker, JSON y SHA-256.

**Spec:** `docs/superpowers/specs/2026-10-04-fase3-coach-analysis-design.md`; protocolo `docs/restructuring/fase3_evaluacion/v1/`.

## Global Constraints

- V1 se conserva íntegro. Cambiar preguntas, hechos, expectativas, mapa, presupuestos o umbral exige versión nueva antes de generar.
- Modelo `garmin-coach:9b`, temperatura 0, 900 tokens analíticos, timeout 600 s y un intento por pregunta. Registrar digest y configuración efectiva antes de ejecutar.
- Seis preguntas en tres pares y nueve controles según `rubric.json`; no excluir casos desfavorables.
- `max_focus_findings=3`, `max_follow_ups=1`, más dependencias obligatorias, para ambos selectores.
- Una sola llamada por pregunta incluye todos sus componentes. Sin reparación, reintento automático ni sustitución de salida inválida.
- Fallos de transporte quedan como `no_evaluado`, registrados y sin autorizar conservar el modelo. Selecciones inválidas cuentan como fallos del modelo.
- Clave separada hasta cerrar puntuaciones y justificaciones. Sin puntuaciones completas, decisión pendiente.
- No importar `ai_worker` ni cargar secretos para ejecutar el arnés. No escribir en servicios, activar flags, desplegar ni modificar alias.
- Ambos flags permanecen apagados por defecto. E14 continúa parcial; PostgreSQL y cierre global no se certifican aquí.
- Mantener la limitación conocida de E10-mixto y los ámbitos sin resolver; no modificar frases o inventar fechas para mejorar resultados.

## Review Focus

- Deriva del digest/configuración durante la corrida: detener y conservar resultados parciales (tarea 2).
- JSON duplicado, campos extra o IDs de otro componente: rechazar sin reparar (tarea 1).
- Interrupción y directorio ya existente: conservar evidencia y evitar sobrescritura o llamadas duplicadas (tarea 2).
- Metadatos que revelan origen en la revisión: exportar solo campos permitidos (tarea 3).
- Puntuaciones incompletas, duplicadas o fuera de 0–2: no emitir victoria (tarea 3).

### Tarea 1: Preparación común y contrato de selección

**Files:** Crear `docs/restructuring/fase3_evaluacion/experiment.py` y `test_experiment.py`.

**Interfaces:** `prepare_cases(protocol_dir: Path) -> list[dict]`; `parse_selections(raw: str, catalogs: tuple) -> tuple[AnalysisSelection, ...]`; `render_candidate(catalogs: tuple, selections: tuple) -> str`.

- [ ] Escribir pruebas que verifiquen sello V1, los 15 casos de comparación, reloj/pregunta originales e igualdad de snapshots y catálogos entre selectores. Los pares mantienen hechos idénticos.
- [ ] Añadir rechazo de campos extra, claves duplicadas, componentes ausentes/repetidos, IDs ajenos, presupuesto excedido y dependencia de seguridad omitida. Afirmar que no hay reparación ni selección implícita.
- [ ] Ejecutar `apps/sync-local/.venv/bin/python -m unittest discover -s docs/restructuring/fase3_evaluacion -p 'test_experiment.py' -v`; comprobar fallo por interfaz ausente.
- [ ] Implementar interfaces usando `verify`, `materialize`, `build_snapshot`, `build_catalog`, `select_findings`, `validate_selection` y `render_selection`. El montaje de aclaraciones/consejo es común y conserva el comportamiento de `deterministic_response`; extraer helper compartido solo si es necesario, cubierto por regresiones existentes.
- [ ] Repetir pruebas hasta PASS y registrar baseline determinista antes de llamar al modelo. Comprobar equivalencia del texto de baseline con la ruta actual, incluidas aclaraciones y casos mixtos.

### Tarea 2: Cliente Ollama y corrida inmutable

**Files:** Crear `docs/restructuring/fase3_evaluacion/experiment_ollama.py` y `test_experiment_ollama.py`; ampliar `experiment.py` con CLI.

**Interfaces:** `inspect_model(base_url: str, model: str) -> dict`; `generate_selection(base_url: str, payload: dict) -> str`; `run_experiment(protocol_dir: Path, output_dir: Path, base_url: str) -> dict`.

- [ ] Escribir pruebas con HTTP simulado: parámetros exactos, una petición por pregunta con todos los componentes, timeout, HTTP fallido, JSON inválido, digest cambiado y rechazo de directorio existente. Verificar que una interrupción conserva cada resultado terminado y no reejecuta automáticamente.
- [ ] Ejecutar `apps/sync-local/.venv/bin/python -m unittest discover -s docs/restructuring/fase3_evaluacion -p 'test_experiment_ollama.py' -v`; comprobar fallo esperado.
- [ ] Implementar cliente independiente con httpx y esquema estricto. Guardar antes de generar hashes del protocolo, prompt/esquema, código y configuración, digest y baseline. No leer `.env`; usar argumentos explícitos para el endpoint local.
- [ ] Registrar por caso selección o categoría de error, latencia y huellas; no preguntas crudas ni datos privados en logs técnicos. Los paquetes de revisión obtienen las preguntas sintéticas del protocolo.
- [ ] Repetir pruebas hasta PASS. Verificar que fallos no llaman a la ruta de reserva ni a persistencia.

### Tarea 3: Revisión ciega y cálculo del resultado

**Files:** Crear `docs/restructuring/fase3_evaluacion/experiment_review.py` y `test_experiment_review.py`.

**Interfaces:** `export_blind(run_dir: Path, review_dir: Path, key_path: Path) -> None`; `seal_ratings(review_dir: Path, ratings_path: Path) -> str`; `evaluate_ratings(run_dir: Path, ratings_path: Path, key_path: Path) -> dict`.

- [ ] Escribir pruebas de IDs opacos y orden aleatorio, ausencia de origen/latencia en paquete ciego, clave fuera del paquete y cierre de puntuaciones con hash antes de revelar correspondencia.
- [ ] Probar victoria solo con seis U estrictamente mayores, F/P/R sin retrocesos, expectativas cumplidas y controles válidos. Un empate conserva determinista; transporte no evaluado o puntuación ausente impide victoria. Rechazar IDs duplicados/desconocidos, notas vacías y valores fuera de 0–2.
- [ ] Ejecutar `apps/sync-local/.venv/bin/python -m unittest discover -s docs/restructuring/fase3_evaluacion -p 'test_experiment_review.py' -v`; comprobar fallo esperado.
- [ ] Implementar exportación, sellado y evaluación conforme a la rúbrica V1. Incluir hechos y expectativas para puntuar, sin revelar la clave antes del sellado. Si no hay revisor ciego disponible, entregar paquete pendiente y declarar ese límite; no simular una revisión independiente.
- [ ] Repetir pruebas hasta PASS.

### Tarea 4: Verificación y ejecución local

**Files:** Actualizar `docs/restructuring/fase3_evaluacion/README.md`; crear directorio único en `docs/restructuring/fase3_evaluacion/ejecuciones/` para resultados y un informe de estado.

- [ ] Ejecutar `apps/sync-local/.venv/bin/python docs/restructuring/fase3_evaluacion/verify_protocol.py`; exigir cero errores y sello publicado sin cambios.
- [ ] Ejecutar `apps/sync-local/.venv/bin/python -m unittest discover -s docs/restructuring/fase3_evaluacion -p 'test_*.py' -v`; exigir PASS.
- [ ] Ejecutar desde `apps/sync-local`: `.venv/bin/python -m unittest discover -s tests -p 'test_coach*.py' -v`; exigir PASS y registrar alcance real de regresiones.
- [ ] Comprobar disponibilidad y configuración de Ollama local. Si falta modelo o servicio, documentar bloqueo concreto sin descargar modelos ni alterar configuración implícitamente.
- [ ] Ejecutar baseline y una corrida de los 15 casos con cliente real, conservando fallos. Exportar paquete ciego y mantener clave separada; obtener puntuaciones antes de calcular resultado.
- [ ] Documentar estado por caso, latencias, fallos, límites de muestra y revisión, E10-mixto, y ausencia de integración/activación. No declarar cierre de fase 3 ni decisión favorable con evaluación pendiente.
- [ ] Actualizar este plan con evidencia de lo ejecutado y los pendientes reales. Decisión e integración eventual pertenecen al entregable 5.
