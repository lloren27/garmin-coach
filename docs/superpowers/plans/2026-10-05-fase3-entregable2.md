# Fase 3 — Entregable 2: hechos deterministas

Objetivo: `build_analysis_facts(snapshot, component_index=0) -> AnalysisFacts`
en `apps/sync-local/garmin_sync/coach_analysis.py`. Consume exclusivamente el
snapshot validado, sin red, reloj global, escrituras ni decisiones de plan.
Contratos congelados, referencias a evidencia/sesiones, fechas `date`, magnitudes
con unidad y derivaciones con operandos. La salida pertenece a un componente.

El módulo construye hechos para las fechas observadas del componente; no toma
prestadas fechas de consejo ni de otro componente. Sin ámbito observado devuelve
ámbito sin resolver, sin inventar hechos. Para latest se usa el último día de
actividad; si varias actividades comparten ese día y se pide una sola, declara
ambigüedad porque el snapshot no conserva la hora de inicio. No se elige por ID.

Correspondencia por día y deporte: vínculo confirmado válido, varias parejas,
datos insuficientes, pareja única dentro/fuera de banda. La falta de plan se
expresa como ausencia en el snapshot; no se afirma ausencia global. La ausencia
de actividad solo se certifica con cobertura explícita del día y sin errores.

La indisponibilidad, frescura y síntomas se preservan del snapshot, sin volver a
implementar proveedores ni recuperar texto libre descartado. No se concluye
recuperación, intensidad o tendencia a partir de observaciones aisladas. Los
hallazgos/renderizado/selector pertenecen al entregable 3.

- [x] Pruebas de hechos con entradas congeladas y variantes, antes del módulo.
- [x] Contratos, comparaciones y correspondencia puras con trazabilidad.
- [x] Cobertura, ámbito, bienestar y síntomas sin inferencias prescriptivas.
- [x] Tests nuevos, regresiones de contexto/intención y verificación del sello V1.

Revisión: cubrir confirmación conflictiva, rangos inválidos, cero/negativos/NaN,
varias sesiones/actividades, medianoche UTC, dos componentes, datos de días
ajenos, inmutabilidad profunda y referencias derivadas resolubles. No se ejecuta
el experimento de selectores ni Ollama en este entregable.

## Resultado

Implementación en rama `codex/fase3-hechos-deterministas`, conservando los cambios
anteriores. Se añadieron 27 tests de hechos: primero se observó fallo por módulo
ausente; después se corrigieron dependencia del redondeo Decimal externo y la
interpretación incorrecta de un rango incompleto como objetivo escalar.

Regresiones verificadas: 68 tests de generación/contexto y 46 de intención.
Verificador del protocolo V1 sin errores. No se cambian sus fixtures ni hashes.
Los casos sintéticos adicionales de los tests son pruebas unitarias de bordes,
no cambios del corpus de evaluación ni resultados del experimento de selectores.

Decisiones de implementación: Decimal con contexto local fijo; un rango de
duración requiere ambos extremos válidos (un escalar de duración puede
representarse con extremos iguales). Distancia usa objetivo escalar explícito.
Los vínculos confirmados conflictivos/ausentes no se degradan a candidatos.
Fuentes secundarias, frescura y cobertura se conservan; cada derivación referencia
hechos operandos del mismo componente. Los hechos de consejo futuro no se
convierten en observaciones. La selección de hallazgos y la limitación verbal de
seguridad se implementarán en el entregable 3 usando estos hechos, no aquí.

Límites comprobados del snapshot: la molestia se recibe como booleano, sin
localización ni texto; la última actividad no puede desempatarse por hora.
El módulo declara esos límites sin ampliar el contrato ni inventar información.
No certifica un baseline de bienestar: registra que no se ha establecido. La
ausencia de plan se refiere solo a las sesiones disponibles en el snapshot.

No se han conectado rutas de producción, activado flags, llamado a Ollama ni
ejecutado pruebas de PostgreSQL. Revisión local, sin revisión independiente.
