# Fase 2 v1: intención correcta y conclusiones fundamentadas del coach

> Ejecución: aplicar `superpowers:executing-plans` tarea a tarea, con pruebas de regresión antes de cada cambio. Este documento define el plan; no inicia su implementación.

**Objetivo:** que «analiza mi entrenamiento de hoy» valore lo realizado, explique su relación con el plan y concluya qué se puede afirmar con los datos disponibles.

**Arquitectura:** resolver la intención y las fechas antes de generar; calcular hechos y comparaciones en Python; permitir que Ollama seleccione conclusiones verificables y su prioridad dentro de ese ámbito. El renderizador construye una explicación conectada a esas conclusiones, con límites explícitos y sin una segunda prescripción independiente.

**Tecnología:** Python, Pydantic, FastAPI, Ollama y las suites unittest existentes.

**Referencias:** [Fase 1 v1](restructuring_fase1_v1.md), [informe Fase 0](fase0_resultados/informe_2026-10-04.md), [revisión manual](fase0_resultados/ejecuciones/2026-10-04-ollama/revision_manual.md) y caso real descrito abajo.

Fecha: 4 de octubre de 2026. Estado: propuesta para revisión. Checkout inspeccionado: `d7f2293fe176793c65e83994186d4fdbbaeff610`. Esto no identifica por sí solo el código que ejecutan Railway ni el worker local.

## 1. Problema y resultado esperado

El usuario pidió analizar la actividad del 04/10. La respuesta presentó una sesión prevista de 17 km y enumeró una carrera registrada de 11,01 km en 3353 segundos, pulso medio 136 y máximo 164. No comparó volúmenes ni produjo una conclusión.

En el código actual:

- `generation_schema` permite `keep_plan` cuando hay sesiones en la fecha, aunque la pregunta sea de análisis.
- `activity_analysis` solo se activa cuando todas las decisiones son `information_only` y el tipo es `analysis`.
- Las conclusiones admitidas son demasiado generales; el renderizador usa frases como «Actividad registrada».
- Un único `target_dates` mezcla fechas observadas y fechas de recomendaciones. «Analiza hoy y dime qué hacer mañana» necesita ambas.
- Corregir el formato `5:06/km` evita un rechazo, pero no corrige estos problemas.

Ejemplo de aceptación con los datos aportados, sin asumir correspondencia confirmada:

> Has registrado 11,01 km en 55:53, a unos 5:05/km calculados con la duración registrada. El plan de hoy contiene una carrera de 17 km: si esta actividad corresponde a esa sesión, la distancia fue 5,99 km menor, un 35,2 % menos.
>
> El objetivo de 5:06/km se refiere a bloques del plan; el ritmo medio de toda la actividad no demuestra su cumplimiento. Con el pulso medio y máximo no puedo determinar la intensidad sin referencias personales y distribución del esfuerzo.
>
> Conclusión: la diferencia observable es de volumen. Para interpretar si fue una adaptación deliberada o una sesión incompleta, falta confirmar la correspondencia con el plan y el motivo del recorte.

No se exige esa redacción literal. Sí se exige que responda a la pregunta y justifique la conclusión. La puntuación Zepp 73 y el factor del proveedor 1 no permiten afirmar por sí solos «recuperación óptima».

## 2. Alcance y condiciones

- Prioridad inicial: análisis retrospectivo de una actividad o día. Después, consultas mixtas con orientación futura.
- Mantener consultas de plan, propuestas autorizadas y su aprobación separadas del análisis.
- Fase 1 conserva la responsabilidad sobre identidad, deduplicación, procedencia y frescura. Esta fase consume esos contratos; no mantiene una implementación alternativa.
- Se puede desarrollar con fixtures mientras Fase 1 avanza. La aceptación integral con datos reales requiere sus garantías de procedencia y cobertura. Los campos ausentes se consideran desconocidos.
- No migrar la base por defecto: aprovechar el resultado estructurado de trabajos existente; comprobar primero sus restricciones.
- Fechas inyectables, pruebas aisladas y sin mensajes de prueba al usuario. No guardar preguntas, métricas personales ni respuestas crudas en logs ordinarios.
- Una petición de análisis no autoriza cambios del plan. La intención clasificada tampoco puede ampliar los permisos que concede el backend.
- Las limitaciones documentadas de backup y Zepp siguen vigentes. Si se requiere una migración, aplicar la restauración aislada previa definida en Fase 1.

## 3. Diseño propuesto

### Intención y ámbito

Crear `CoachIntent` con valores `analyze_activity`, `analyze_day`, `consult_plan`, `recommend_next`, `request_change`, `mixed` y `clarify`.

Crear `IntentResolution`: intención principal, componentes ordenados para consultas mixtas, selector (`by_date`, `latest_activity`, `latest_training_day`), `observed_dates`, `advice_dates` y motivo de aclaración si falta ámbito.

La resolución es determinista en esta primera versión: reglas explícitas para verbos, negación, fechas y objeto de consulta. `/coach` es un canal, no una intención. Las reglas desconocidas o contradictorias llevan a una aclaración concreta; no se presupone consultar el plan por la mera presencia de sesiones.

«Última actividad» selecciona por instante de inicio disponible, no por el orden de una lista. Un empate sin precisión suficiente es ambiguo. «Hoy» usa Europe/Madrid; no se sustituye silenciosamente por la última sesión de otro día.

### Hechos y correspondencia con el plan

Crear `AnalysisFacts` con actividades seleccionadas, cálculos derivados, cobertura, referencias personales utilizables, candidatos del plan y límites. Cada hecho tiene ID estable dentro del snapshot, unidad, referencias originales, fecha, fórmula cuando corresponda y alcance.

La correspondencia será `confirmed`, `candidate`, `ambiguous` o `none`. Solo un vínculo persistido o confirmación explícita permite `confirmed`. Una única sesión del mismo deporte y día es candidata; varias sesiones no se emparejan automáticamente. No se escribe un vínculo nuevo durante el análisis.

Calcular distancia y duración comparadas, diferencia absoluta y relativa cuando el objetivo sea positivo. Preservar los rangos de duración: por debajo, dentro o por encima del rango; no compararlos con un punto medio inventado. No sumar kilómetros de bici y carrera como carga equivalente.

Conservar el alcance del ritmo previsto: global, por bloques o desconocido. Sin bloques comparables no se concluye cumplimiento de ritmo. Sin zonas/referencias personales y distribución o sensaciones suficientes no se clasifica la intensidad con dos valores de pulso.

### Conclusiones verificables

Añadir un contrato interno versionado de análisis con `findings`, `limitations` y `follow_up`. Un finding contiene `code`, `fact_refs` y una certeza discreta (`observed`, `conditional`, `unavailable`), no números ni hechos libres del modelo.

Catálogo inicial: `VOLUME_BELOW_PLAN`, `VOLUME_WITHIN_PLAN`, `VOLUME_ABOVE_PLAN`, `PLAN_MATCH_UNCONFIRMED`, `NO_PLAN_FOR_SCOPE`, `PACE_BLOCKS_NOT_COMPARABLE`, `INTENSITY_NOT_ASSESSABLE`, `HISTORY_INSUFFICIENT` y `MULTISPORT_TOTALS_ONLY`.

Python calcula cuáles están justificadas. Ollama selecciona y ordena las conclusiones admisibles; el validador verifica referencias, ámbito y precondiciones. Al menos una conclusión relevante debe aparecer; si faltan datos, la conclusión explica la limitación concreta. No se puede aprobar una salida compuesta solo de observaciones.

El renderizador enlaza hecho, significado y límite. La variedad de redacción puede crecer después, pero una referencia válida no se considera prueba automática de cualquier prosa libre. La versión inicial prioriza conclusiones comprobables frente a ampliar el contrato con texto imposible de verificar de forma determinista.

En análisis puro no se genera una nueva sesión. En consultas mixtas, análisis y recomendación comparten los mismos hechos, pero cada parte conserva sus fechas. Si no existe fundamento para orientar la siguiente sesión, se explica qué falta en lugar de inventar una dosis.

## 4. Tareas de implementación

### Tarea 1 — Resolver intención y fechas

Crear `apps/sync-local/garmin_sync/coach_intent.py` y `apps/sync-local/tests/test_coach_intent.py`.

Interfaz: `resolve_intent(question: str, *, now: datetime) -> IntentResolution`. La selección concreta de la actividad se realiza con los datos en la tarea 3.

- [ ] Escribir pruebas: «analiza mi entrenamiento de hoy» → `analyze_day`; «última actividad» → `analyze_activity`; «qué toca mañana» → `consult_plan`; «analiza hoy y dime qué hacer mañana» → `mixed` con fechas separadas.
- [ ] Añadir negaciones («no cambies el plan, analiza hoy»), varias sesiones, fechas ISO y dd/mm/aaaa, «ayer», semana pasada y cruce de medianoche. Petición sin fecha ni selector → aclaración cuando el objeto no pueda determinarse.
- [ ] Ejecutar las pruebas y comprobar los fallos esperados; implementar las reglas e inyección del reloj; repetir hasta pasar.
- [ ] Revisar y registrar este cambio como unidad independiente.

### Tarea 2 — Imponer la intención en contrato y validación

Modificar `coach_generation_context.py`, `coach_generation_contracts.py`, `coach_generation_resolver.py`, `coach_generation_pipeline.py` y `ai_worker.py` en `apps/sync-local/garmin_sync/`. Ampliar sus tests existentes.

Interfaz: el snapshot contiene `intent: IntentResolution`; `generation_schema(snapshot)` limita acciones por componente. La resolución vuelve a comprobar esa restricción incluso si el modelo ignora el esquema.

- [ ] Probar que un `keep_plan` inyectado en análisis retrospectivo se rechaza como `INTENT_MISMATCH`; añadir ese código en `coach_validation.py` con reparación limitada al mismo ámbito.
- [ ] Probar que análisis puro solo admite `information_only` o aclaración, y mantiene `change_proposal=null`; consultas de plan siguen admitiendo `keep_plan`.
- [ ] Separar fechas de observación y consejo: analizar ayer es válido, prescribir para ayer no. Probar «hoy 2026-10-04 y mañana» sin perder ninguna fecha.
- [ ] Ejecutar en rojo, implementar restricciones y prompts por intención, verificar en verde. Ajustar presupuesto de generación por intención, no por la palabra «plan».
- [ ] Mantener autorización del backend independiente de `request_change`; probar una clasificación manipulada sin permisos.

### Tarea 3 — Construir hechos y comparaciones

Crear `apps/sync-local/garmin_sync/coach_analysis.py` y `apps/sync-local/tests/test_coach_analysis.py`. Integrar con el snapshot de contexto.

Interfaz: `build_analysis_facts(snapshot: ContextSnapshot) -> AnalysisFacts`. Este módulo es puro: no llama a proveedores, no persiste ni decide prescripciones.

- [ ] Probar el fixture 11,01 km / 3353 s frente a 17 km: 55:53, ritmo redondeado 5:05, diferencia −5,99 km y −35,2 %, match candidato sin vínculo.
- [ ] Probar actividad confirmada por ID, varias actividades/planes ambiguos, ausencia de plan, ausencia de actividad con cobertura desconocida y duraciones faltantes o cero.
- [ ] Probar rangos de duración, objetivo por bloques, datos antiguos, histórico insuficiente, carrera+bici+fuerza sin carga equivalente inventada y última actividad sin orden fiable de entrada.
- [ ] Ejecutar en rojo, implementar cálculos con unidades y procedencia, verificar en verde. La evidencia sin procedencia fiable no recibe un proveedor por defecto.

### Tarea 4 — Expresar conclusiones fundamentadas

Modificar contratos, resolver y renderer de generación. Crear `apps/sync-local/tests/test_coach_analysis_response.py`.

Interfaces: `AnalysisFinding(code, fact_refs, certainty)` y `AnalysisSelection(findings, limitations, follow_up)`; `validate_analysis(selection: AnalysisSelection, facts: AnalysisFacts) -> AnalysisSelection`; `render_analysis(selection: AnalysisSelection, facts: AnalysisFacts) -> str`.

- [ ] Probar que se rechaza «volumen cumplido» cuando 11,01 < 17, certeza observada con match candidato, referencias ajenas y selección vacía cuando hay una comparación relevante.
- [ ] Probar que no se afirma intensidad suave por FC media 136, recuperación óptima por score 73/factor 1, ni cumplimiento de bloques por ritmo medio 5:05.
- [ ] Implementar el catálogo y sus precondiciones, incorporarlo al esquema y resolver. Resumen breve → comparación → conclusión → límite/pregunta pertinente, sin volcado de fases del sueño salvo relevancia demostrada.
- [ ] Probar que la respuesta conserva conclusión y condiciones bajo el límite de caracteres y que las métricas renderizadas coinciden con los hechos calculados.
- [ ] Verificar las pruebas en verde; revisión manual del caso real y de un caso sin comparación posible. No introducir un catálogo que vuelva a producir solo «actividad disponible».

### Tarea 5 — Unificar entradas y respuesta de reserva

Modificar `apps/bot/app/main.py`, los alias de `apps/bot/app/coach.py` y `apps/sync-local/garmin_sync/ai_worker.py`. Ampliar `apps/bot/tests/test_coach_routing.py` y `apps/sync-local/tests/test_ai_response_flow.py`.

- [ ] Probar la equivalencia de texto libre, `/coach` y voz transcrita. `/feedback` encola «analiza todas las actividades del último día de entrenamiento», con el selector explícito correspondiente.
- [ ] Hacer que el fallback de análisis use los mismos `AnalysisFacts` y conclusiones verificadas, identificándose como respuesta de reserva. El fallo de Ollama no debe activar una prescripción heredada de 40–55 minutos ajena a la pregunta.
- [ ] Probar timeout, JSON inválido, reparación agotada y contexto insuficiente. Mantener un máximo de una reparación, sin reiniciar el presupuesto indefinidamente.
- [ ] Probar que consulta, fallback y reintento no alteran IDs, revisión ni sesiones del plan, y que la entrega del resultado conserva la idempotencia existente.
- [ ] Verificar las pruebas en verde y compatibilidad de trabajos pendientes sin intención almacenada: resolverla al ejecutarlos.

### Tarea 6 — Evaluación y despliegue verificable

Ampliar `docs/restructuring/fase0_resultados/evaluar.py` y los fixtures sanitizados; crear un informe de Fase 2 separado. No reescribir evidencias de Fase 0.

- [ ] Añadir el caso real aportado como fixture sin identificadores privados y guardar respuestas esperadas por propiedades, no por redacción literal.
- [ ] Repetir E01, E07, E08, E09, E10, E13 y el caso real tres veces con Ollama. Registrar intención, componentes, resultado, reparaciones y latencia; distinguir éxito del modelo de fallback.
- [ ] Revisión manual por ejecución: responde a la pregunta, conclusión explícita, razones trazables, ausencia de contradicciones y límites proporcionales. Una respuesta con números correctos y sin conclusión suspende.
- [ ] Ejecutar suites aisladas de bot y worker; contabilizar pruebas nuevas. El fallo previo de fecha fija debe resolverse en Fase 1 antes de declarar todo en verde; las omisiones PostgreSQL no cuentan como aprobación.
- [ ] Documentar contrato interno nuevo y adaptación a `CoachStructuredResponse`. Mantener el formato externo existente si contiene todo lo necesario; cualquier ampliación requiere lector compatible antes del worker productor.
- [ ] Preparar rollback compatible con trabajos pendientes; verificar SHA del backend y revisión del worker local por separado. Desplegar solo dentro de la autorización de ejecución correspondiente.

## 5. Verificación ejecutable

Desde la raíz, usar el runner aislado existente con etiquetas nuevas, por ejemplo:

```sh
apps/sync-local/.venv/bin/python docs/restructuring/fase0_resultados/ejecutar_suite.py worker --run=fase2-worker-01
apps/sync-local/.venv/bin/python docs/restructuring/fase0_resultados/ejecutar_suite.py bot --run=fase2-bot-01
```

Para PostgreSQL, añadir `--audit-db-port` con el puerto real de la base desechable, nunca de producción. Para los ciclos dirigidos usar unittest con las dependencias de ambos entornos y dobles de I/O; no ejecutar el worker operativo como prueba, porque reclama trabajos reales.

## 6. Revisión y criterio de cierre

Revisar especialmente estas cinco situaciones, cubiertas por las tareas indicadas:

1. Análisis con un plan presente: no debe sustituir el balance de lo realizado por `keep_plan` (tareas 1–2).
2. Hoy y mañana en la misma consulta: conservar observación y consejo separados (tareas 1–2).
3. Varias actividades y bloques: no fabricar correspondencias ni cumplimiento (tareas 3–4).
4. Fuente sin cobertura o sin referencias personales: explicación limitada, nunca diagnóstico por inferencia (tareas 3–4).
5. Ollama falla o se reintenta la entrega: reserva útil, misma intención y plan intacto (tarea 5).

Cerrar cuando todas las regresiones deterministas pasan y las 21 ejecuciones de Ollama producen una respuesta válida y útil según su caso, sin fallback encubierto, hechos inventados ni modificaciones no autorizadas. Un resultado insuficiente se registra y corrige; no se compensa promediándolo con otros casos.

El primer hito demostrable será que la consulta real reciba una comparación y una conclusión condicionada por la correspondencia con el plan. No hace falta resolver todas las futuras recomendaciones fisiológicas para entregar ese valor.
