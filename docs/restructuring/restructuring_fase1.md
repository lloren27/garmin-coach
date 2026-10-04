# Fase 1: plan de implementación (datos coherentes de extremo a extremo)

Fecha: 3 de octubre de 2026. Estado: borrador para revisión. Parte del informe de la Fase 0 (checkout `b6912b94`).

## 1. Objetivo y salida

Que una misma actividad y una misma medición conserven su identidad y su procedencia desde la recogida hasta el contexto del entrenador, y que el contexto diga con claridad qué falta o está desactualizado.

**Salida:** E02, E03, E05, E06, E16 y E17 pasan como regresiones automáticas; E04 sigue pasando; E11 queda corregido por separado.

## 2. Alcance

**Dentro:**

- 1.0 `/plan` deja de guardar al consultar (E11), como cambio pequeño e independiente.
- 1.1 Reloj inyectable y arreglo del test frágil.
- 1.2 Procedencia Strava en contexto y contratos (E03).
- 1.3 Deduplicación con vínculo auditable a todos los orígenes (E02, E04).
- 1.4 Estado por proveedor y frescura en el contexto (E05, E06).
- 1.5 Disponibilidad de Wattwise en el contexto (E17).
- 1.6 Fechas, medianoche y cambio horario (E16).

**Fuera (fases posteriores):** unificar el enrutamiento (E14), ampliar el contrato de Ollama, contexto por fechas y pregunta, vinculación sesión-plan, rediseño de comandos y `/registro`, extracción de módulos.

## 3. Reglas

- Mismo aislamiento que la Fase 0: pruebas locales, almacenamiento temporal y dobles para Telegram y proveedores. Ningún mensaje de prueba al usuario.
- Cada cambio es un conjunto independiente con su prueba: primero el caso falla, luego pasa. Cada uno se puede revertir sin los demás.
- Migraciones solo aditivas. Antes de cambiar el esquema: copia de seguridad y restauración verificada en una base aislada.
- No se borran ni reescriben datos históricos.
- Compatibilidad entre API y worker: quien lee acepta el valor nuevo antes de que quien escribe lo produzca, y los trabajos pendientes siguen siendo válidos.
- No se despliega sin cumplir los prerrequisitos de la sección 4 y sin confirmación explícita.

## 4. Prerrequisitos

1. **Commit desplegado en Railway.** Comprobarlo en el panel (sin CLI ni endpoints) y compararlo con `b6912b94`. Si difiere, se audita la diferencia antes de nada, porque los hallazgos de `/plan` y `/feedback` están en código del bot.
2. **Cobertura por proveedor** (Fase 0, paso 0.5): tabla de Garmin, Strava y Zepp con cobertura confirmada, ausencia confirmada o desconocida. Es lo que alimenta el diseño de 1.4.
3. **Reloj inyectable** (1.1), para que los casos no cambien según el día de ejecución.
4. **PostgreSQL aislado** operativo, para ejecutar las 5 pruebas omitidas y verificar migraciones.

La repetición de Ollama de la Fase 0 **no bloquea** la Fase 1 (los cambios son deterministas), pero sí debe estar hecha antes de la Fase 2.

## 5. Cambios, en orden

### 1.1. Reloj inyectable y test frágil

- Localizar dónde el código toma la fecha actual y permitir inyectarla.
- Corregir `test_build_payload_imports_strava_activity_from_sixty_day_window` fijando el reloj, no cambiando el producto.
- Fijar fecha y zona horaria en el evaluador.
- _Hecho cuando:_ worker con 0 fallos y evaluador reproducible con fecha fija.

### 1.0. `/plan` consulta sin escribir (E11)

- Consultar lee el plan vigente persistido. Si no hay ninguno, lo dice.
- La creación (`build_week_plan` y `save_training_plan`) queda tras una intención explícita. El nombre queda pendiente (sección 8).
- Las versiones ya creadas por consultas anteriores **no se borran**. Se puede marcar su origen si es identificable, sin eliminarlas.
- Riesgo: si algún flujo depende de que `/plan` cree el plan, hay que mantener esa vía accesible con la intención explícita.
- _Prueba:_ consultar N veces no cambia identificador, revisión ni sesiones.
- _Marcha atrás:_ revertir el enrutamiento, sin tocar datos.

### 1.2. Procedencia Strava (E03)

- Admitir `strava` como origen en el contexto validado (`coach_generation_context.py`).
- Dejar de normalizar `source=strava` a `garmin` en `build_snapshot`, y sustituir la alternativa «Garmin» por un valor `desconocido` explícito.
- Conservar proveedor y dispositivo cuando se conozcan.
- Contratos bot/worker: ampliar el conjunto de valores aceptados en ambos y desplegar primero el lector.
- Presentación: la respuesta atribuye la sesión a su fuente real.
- _Prueba:_ E03; el test existente de importación Strava sigue verde.
- _Marcha atrás:_ revertir el código. Los datos nuevos con `strava` deben seguir leyéndose sin error.

### 1.3. Deduplicación con vínculo auditable (E02, E04)

- `activity_merge` devuelve el registro principal **y** la lista de originales: proveedor, identificador externo, dispositivo.
- Regla de coincidencia candidata de la Fase 0 (inicio, duración, distancia, deporte), con tolerancias explícitas. Las coincidencias ambiguas quedan visibles, no resueltas en silencio.
- Persistencia aditiva del vínculo (tabla o campo nuevo; se decide en el plan técnico) con copia de seguridad previa.
- _Prueba:_ E02 (una vez contada, ambos orígenes conservados) y E04 (dos sesiones del mismo día siguen separadas), más casos ambiguos de la muestra real.
- _Marcha atrás:_ el vínculo es aditivo; revertir el código lo ignora.

### 1.4. Estado por proveedor y frescura (E05, E06)

- Registrar por proveedor: último intento, último éxito, periodo cubierto y error.
- Un fallo de un proveedor no detiene a los demás.
- Reconsultar días recientes, sin duplicar (E05).
- Distinguir en el contexto: «sin actividad», «sin datos», «datos antiguos» y «error del proveedor», con fecha del dato y fecha de recogida.
- Vista de solo lectura del estado (la presentación definitiva de `/estado` queda para la Fase 4).
- _Prueba:_ E05 con reconsulta simulada de Zepp; E06 con un proveedor en error; el contexto incluye el estado como evidencia.
- _Marcha atrás:_ campos aditivos; la vista se puede retirar sin efecto.

### 1.5. Wattwise en el contexto (E17)

- Representar «Wattwise no disponible» con motivo y fecha, para que el entrenador pueda explicarlo.
- _Prueba:_ E17.

### 1.6. Fechas, medianoche y cambio horario (E16)

- Completar la prueba con sueño de Zepp y su deduplicación (hoy solo cubre Strava).
- Casos alrededor de medianoche y del cambio horario del 25 de octubre de 2026 (fin del horario de verano en Europa).
- Guardar zona horaria junto a la fecha observada.
- _Prueba:_ E16 completo. El cambio horario real es una ocasión de comprobarlo con datos reales sin forzarlo.

## 6. Pruebas y aceptación

| Caso | Resultado esperado al cerrar la fase                                                      |
| ---- | ----------------------------------------------------------------------------------------- |
| E02  | Una actividad contada una vez, con vínculo a ambos orígenes.                              |
| E03  | La sesión CMF se atribuye a Strava en contexto y respuesta.                               |
| E04  | Dos sesiones del mismo día siguen separadas.                                              |
| E05  | La reconsulta actualiza el día sin duplicar.                                              |
| E06  | El fallo de un proveedor llega al contexto como evidencia y los demás datos se conservan. |
| E11  | Consultar el plan no crea versiones.                                                      |
| E16  | Fechas correctas en medianoche y cambio horario, también para Zepp.                       |
| E17  | La ausencia de Wattwise queda expresada en el contexto.                                   |

Además: bot (81) y worker (151) en verde; las 5 pruebas omitidas ejecutadas con PostgreSQL aislado; línea base de la Fase 0 repetida y comparada, sin regresiones en los casos que pasaban.

## 7. Migración y despliegue

- Copia de seguridad y restauración verificada antes de cualquier cambio de esquema.
- Orden por cambio: migración aditiva, lector compatible, productor del valor nuevo.
- Los datos históricos con origen `garmin` que en realidad vinieron de Strava **no se reescriben**. Solo se reclasifican si el identificador externo permite determinarlo con certeza (decisión pendiente).
- Cada despliegue es explícito, con ruta de vuelta a la versión anterior compatible con los datos migrados, y se verifica con datos sintéticos, no con mensajes de prueba al usuario.

## 8. Decisiones pendientes

| Decisión                                                  | Afecta a | Propuesta                                                                  |
| --------------------------------------------------------- | -------- | -------------------------------------------------------------------------- |
| Nombre y forma de la intención de crear plan              | 1.0      | Subcomando explícito, por ejemplo `/plan nuevo`.                           |
| ¿Reclasificar actividades históricas atribuidas a Garmin? | 1.2      | Solo si el identificador externo lo demuestra.                             |
| Regla final de coincidencia Garmin/Strava                 | 1.3      | Partir de la regla candidata de la Fase 0 y ajustarla con la muestra real. |
| ¿Zepp sigue importando actividades?                       | 1.3, 1.4 | Decidir con la tabla de cobertura.                                         |
| Dónde vive la vista de estado                             | 1.4      | Solo lectura, sin comando nuevo hasta la Fase 4.                           |

## 9. Riesgos

- **Railway no versionado:** puede desplegar código distinto al auditado. Mitigación: prerrequisito 1.
- **Cobertura desconocida:** diseñar 1.4 sin saber qué falla en la recogida real. Mitigación: prerrequisito 2.
- **Fusiones erróneas** en deduplicación. Mitigación: ambigüedad visible y casos reales de la muestra.
- **Alcance:** cualquier cambio de enrutamiento o de contrato de Ollama se aplaza a la Fase 2 o 3.

## 10. Criterio de cierre

La fase termina cuando los casos de la sección 6 pasan, las migraciones están verificadas con copia restaurada, la compatibilidad API-worker está comprobada con trabajos pendientes, los cambios tienen ruta de vuelta documentada, y el informe recoge lo que no se pudo observar.
