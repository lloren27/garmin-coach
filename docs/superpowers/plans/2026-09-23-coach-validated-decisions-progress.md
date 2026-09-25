# Continuación: decisiones validadas del coach

Actualizado: 2026-09-25. Implementación parcial, no integrada ni desplegada.

## Ubicación y base

- Worktree: `/Users/lloren27/Projects/garmin-coach/.worktrees/coach-validated-decisions`.
- Rama: `codex/coach-validated-decisions`.
- Base: `ca7856a` (incluye cambios de importación de actividades Zepp posteriores al diseño).
- Contratos: commit `c1b8299`. El siguiente commit guarda contexto/resolución y este documento.
- Plan: `docs/superpowers/plans/2026-09-23-coach-validated-decisions.md`.
- Especificación: `docs/superpowers/specs/2026-09-23-coach-validated-decisions-design.md`.
- Ledger detallado: `.superpowers/sdd/2026-09-23-coach-validated-decisions/progress.md` dentro del worktree.

Usuario autorizó ejecución directa y pidió avanzar hasta el límite de cinco horas dejando un punto fácil de retomar. Se guarda al 94 % consumido para evitar una interrupción antes del commit. No gastar créditos de reinicio sin autorización específica.

## Implementado y comprobado

1. `coach_generation_contracts.py`: contrato interno v1, snapshot obligatorio, ocho acciones discriminadas, descanso sin objetivos, keep_plan solo por ID, actividades con duración/intensidad/ritmo acotados, conclusiones tipadas y propuestas internas. El contrato público permanece intacto.
2. `coach_validation.py`: códigos/fases/severidades, hints y excepción sin volcar el contenido del modelo.
3. `coach_generation_context.py`: instantánea separada y recursivamente inmutable; catálogo inicial numérico con procedencia; sesiones por ID; ámbitos hoy/mañana/semana/siete días/próximo; esquema con identidad y permiso de propuestas.
4. `coach_generation_resolver.py`: identidad, referencias, resolución exacta de keep_plan, rechazo de duplicados/fechas/cancelaciones, comprobaciones iniciales de conclusiones y adaptación inicial de propuestas.
5. Tests nuevos: 7 de contratos + 12 de contexto/resolución, todos verdes tras ejecución previa en rojo.

Esto NO completa la tarea 2 ni el flujo entero. Los módulos nuevos todavía no están importados por `ai_worker`; no afectan al servicio activo.

## Verificación más reciente

Desde `apps/sync-local`, con el intérprete del checkout original:

```sh
/Users/lloren27/Projects/garmin-coach/apps/sync-local/.venv/bin/python -m unittest discover -s tests -p 'test_coach_generation*.py'
```

Resultado: 19 pruebas OK.

Suite completa sync: 113 pruebas, 1 fallo previo idéntico al baseline. `test_activity_merge.ActivityMergeTests.test_zepp_run_enters_common_summary_when_garmin_is_absent` espera 8 km en today con una actividad fija del 24 de septiembre; la ejecución es del 25. No se modificó esa prueba ni producción para ocultarlo.

Suite bot: 79 pruebas, OK, 5 omitidas de PostgreSQL. `git diff --check` sin problemas en cambios revisados. No se ha probado todavía el esquema con Ollama real.

## Próximos pasos, en orden

1. Leer plan, spec y estos límites antes de seguir. Permanecer en el worktree: el checkout principal lo usa el worker programado.
2. Terminar tarea 2 con pruebas primero. Revisar y completar la extracción de los formatos REALES de wellness, perfil, checkins, fuerza, Wattwise, pruebas e historial: la extracción actual es deliberadamente inicial y solo numérica/top-level. Ya se corrigieron `activity.km → distance_km`, `started_at` y wellness `{value, source}` a su métrica concreta. Falta cobertura del resto de formas anidadas, unidades y fechas. No usar prosa libre como hechos.
3. Endurecer resolución: campos esenciales de sesiones incompletas, reglas por deporte/tipo de sesión, cardinalidad/cobertura de consultas, fechas ambiguas, evidencia suficiente y conclusiones `DATA_MISSING`/`RECOVERY_RECOMMENDATION` fundamentadas. No dar la tarea por terminada por los 19 tests actuales.
4. Completar validación de dominio de `GenerationChangeProposal` ANTES de renderizar: operaciones/campos/fechas/revisión/objetivos coherentes. Hoy solo comprueba existencia/estado/duplicado y fuentes. Reutilizar reglas de `PendingChangeValidator` conservando su autoridad independiente, sin inventar permisos. Snapshot no sustituye la revisión del backend.
5. Revisar colisiones e IDs del catálogo y su longitud, validación de fechas del contexto y severidad fatal de datos autoritativos corruptos. `parse_generation` aún no registra normalizaciones: tarea 4 debe emitir los eventos.
6. Implementar tarea 3: `coach_generation_renderer.py`, plantillas deterministas, adaptación pública, límites sin truncar prescripciones, pruebas para múltiples sesiones/análisis/semana/voz. Todavía NO existe.
7. Tarea 4: pipeline + integración en `ai_worker`. Comprobar snapshot y propuestas prohibidas en JSON parseado antes de que un error estructural en otro campo pueda ocultarlos. Repair único con salida rechazada e hints; logs saneados. El generador actual continúa solicitando answer libre hasta esta integración.
8. Tarea 5: suites, test local de Ollama solo con datos sintéticos, compatibilidad de propuestas, docs y revisión independiente final prevista por la guía de ejecución. Sin mensajes de prueba, sin escrituras en planes reales.

## Decisiones registradas

- No se alteró el fallo baseline de actividades Zepp: fuera del alcance y documentado.
- Los encabezados del plan usan `Task N` para que funcionen los scripts de la guía.
- No marcar tareas completas ni activar código parcial. El primer commit es una base de contratos comprobada; contexto/resolución todavía necesita los endurecimientos indicados.
- Preferir preguntas de aclaración ante ámbito temporal ambiguo; no seleccionar la primera sesión.
