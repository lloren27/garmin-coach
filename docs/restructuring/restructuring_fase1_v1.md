# Fase 1: plan de implementación — datos coherentes de extremo a extremo

Fecha: 4 de octubre de 2026. Estado: borrador revisado para ejecución.  
Parte del informe de la Fase 0 y del checkout auditado
`2abba6ae655c2747fa7d7484cdaf34b323c5955c`.

## 1. Objetivo y salida

Conseguir que una misma actividad y una misma medición conserven su identidad,
procedencia y estado desde la recogida hasta el contexto del entrenador, y que el
contexto indique con claridad qué falta, qué está desactualizado y qué proveedor
ha fallado.

La salida de esta fase será una base de datos y un contexto fiables para el
entrenador. La fase no pretende resolver todavía la calidad de la opinión final
de Ollama: esa parte queda planificada para la Fase 2.

## 2. Alcance

**Dentro:**

- 1.0 `/plan` deja de guardar al consultar (E11).
- 1.1 Reloj inyectable y arreglo del test frágil del worker.
- 1.2 Procedencia Strava en contexto y contratos (E03).
- 1.3 Deduplicación con vínculo auditable a todos los orígenes (E02, E04).
- 1.4 Estado por proveedor y frescura en el contexto (E05, E06).
- 1.5 Disponibilidad de Wattwise en el contexto (E17).
- 1.6 Fechas, medianoche y cambio horario en todas las rutas de sueño Zepp (E16).
- Restauración de backup en una base aislada antes de cualquier migración.

**Fuera de esta fase:**

- Unificar el enrutamiento de texto, voz y `/feedback` (E14).
- Ampliar el contrato de Ollama para expresar conclusiones y valoraciones útiles.
- Contexto especializado por fechas y tipo de pregunta.
- Vinculación avanzada entre sesión y plan.
- Rediseño de comandos, `/registro` y extracción de módulos.

La Fase 1 no se considerará una solución completa del coach. La Fase 2 deberá
convertir el contexto fiable en una opinión única, clara y accionable.

## 3. Reglas

- Mismo aislamiento que la Fase 0: pruebas locales, almacenamiento temporal y
  dobles para Telegram y proveedores. Ningún mensaje de prueba al usuario.
- Cada cambio es un conjunto independiente con su prueba: primero el caso falla,
  luego pasa. Cada conjunto debe poder revertirse sin los demás.
- Las migraciones son aditivas. Antes de modificar el esquema se crea una copia
  no destructiva y se restaura en una base aislada; nunca se prueba restaurando
  directamente sobre producción.
- No se borran ni reescriben datos históricos.
- Quien lee acepta el valor nuevo antes de que quien escribe lo produzca, y los
  trabajos pendientes siguen siendo válidos durante el despliegue.
- No se despliega sin cumplir los prerrequisitos de la sección 4 y sin una
  revisión explícita de compatibilidad y reversión.

## 4. Prerrequisitos

1. **Versión desplegada identificable.** Railway muestra actualmente un
   despliegue activo y exitoso (`fix: refactor v1`), pero la evidencia disponible
   no muestra el SHA y `/health` solo devuelve `status=ok`. Antes de empezar se
   debe consultar el detalle del deployment o añadir `/version` para comparar la
   revisión remota con `2abba6ae655c2747fa7d7484cdaf34b323c5955c`.
2. **Cobertura por proveedor.** Mantener una tabla de Garmin, Strava, Zepp y
   Wattwise con cobertura confirmada, ausencia confirmada o estado desconocido.
   Esta tabla alimenta el diseño de 1.4 y evita confundir “sin datos” con “fallo”.
3. **Reloj inyectable.** Debe estar disponible antes de ejecutar cualquier caso
   dependiente de fecha.
4. **PostgreSQL aislado.** La base temporal usada en Fase 0 ya permitió ejecutar
   las cinco pruebas que estaban omitidas: el bot queda en 81/81. Para esta fase
   sigue siendo obligatorio disponer de una base aislada para probar copia,
   restauración y migraciones.
5. **Línea base registrada.** El worker parte de 150/151 pruebas: queda un fallo
   conocido por una expectativa de ventana fija (31/07–29/09 frente a la ventana
   relativa 05/08–04/10). Debe corregirse fijando el reloj del test, sin alterar
   la lógica del producto.

La repetición de Ollama de la Fase 0 ya está terminada. Sus resultados no bloquean
los cambios deterministas de esta fase, pero sus fallos de utilidad bloquean el
cierre funcional de la Fase 2.

## 5. Cambios, en orden

### 1.1. Reloj inyectable y test frágil

- Localizar cada uso de la fecha actual que afecte a ventanas de datos.
- Permitir inyectar fecha y zona horaria en el worker y en el evaluador.
- Corregir `test_build_payload_imports_strava_activity_from_sixty_day_window`
  fijando el reloj del test, no cambiando el producto.
- _Hecho cuando:_ worker con 0 fallos, ejecución reproducible y ventana esperada
  explícita.

### 1.0. `/plan` consulta sin escribir (E11)

- Consultar lee el plan vigente persistido. Si no hay ninguno, lo indica.
- La creación (`build_week_plan` y `save_training_plan`) queda tras una intención
  explícita, por ejemplo `/plan nuevo`.
- Las versiones creadas por consultas anteriores no se borran. Solo se marca su
  origen si puede identificarse sin reescribir el histórico.
- _Prueba:_ consultar N veces no cambia identificador, revisión ni sesiones.
- _Marcha atrás:_ revertir el enrutamiento sin tocar datos.

### 1.2. Procedencia Strava (E03)

- Admitir `strava` como origen en el contexto validado.
- Dejar de normalizar `source=strava` a `garmin` en `build_snapshot`.
- Usar `unknown` cuando no exista proveedor demostrable, sin inventar Garmin.
- Conservar proveedor, identificador externo y dispositivo cuando se conozcan.
- Ampliar contratos de bot y worker; desplegar primero el lector compatible.
- _Prueba:_ E03 y el test existente de importación Strava.
- _Marcha atrás:_ revertir código; los datos nuevos con `strava` deben seguir
  siendo legibles.

### 1.3. Deduplicación con vínculo auditable (E02, E04)

- `activity_merge` devuelve el registro principal y la lista de originales:
  proveedor, identificador externo y dispositivo.
- Aplicar coincidencia candidata usando inicio, duración, distancia y deporte,
  con tolerancias explícitas.
- Las coincidencias ambiguas quedan visibles y no se resuelven en silencio.
- Persistir el vínculo de forma aditiva, con copia y restauración aislada previa.
- _Prueba:_ E02 cuenta una vez y conserva ambos orígenes; E04 mantiene separadas
  dos sesiones del mismo día; añadir casos ambiguos de la muestra real.

### 1.4. Estado por proveedor y frescura (E05, E06)

- Registrar por proveedor: último intento, último éxito, periodo cubierto, error,
  fecha del dato y fecha de recogida.
- Un fallo de un proveedor no detiene a los demás.
- Reconsultar días recientes sin duplicar; E05 debe actualizar el mismo día.
- Distinguir en el contexto `sin actividad`, `sin datos`, `datos antiguos`,
  `error del proveedor` y `proveedor no configurado`.
- Incluir el estado como evidencia del contexto, no solo como texto de interfaz.
- _Prueba:_ E05 con reconsulta simulada de Zepp y E06 con proveedor en error.

### 1.5. Wattwise en el contexto (E17)

- Representar `Wattwise no disponible` con motivo, fecha y alcance del fallo.
- Permitir que los demás proveedores sigan aportando datos.
- _Prueba:_ E17 y comprobación de que la indisponibilidad no desaparece al
  compactar el contexto.

### 1.6. Fechas, medianoche y cambio horario (E16)

- Guardar timestamps absolutos y zona horaria junto a la fecha observada.
- Calcular la duración mediante timestamps UTC o instantes absolutos, nunca
  restando horas locales que puedan repetir una hora.
- Cubrir la ruta directa de API y el fallback de datos de banda de Zepp.
- Añadir casos de medianoche, cambio horario europeo del 25 de octubre de 2026,
  payload incompleto, deduplicación y fechas locales correctas.
- El caso del cambio horario debe demostrar 540 minutos reales, no 480.
- _Prueba:_ E16 completo con duración, fecha, zona, deduplicación y origen.

## 6. Pruebas y aceptación

| Caso | Resultado esperado al cerrar la fase |
| --- | --- |
| E02 | Una actividad contada una vez, con vínculo a ambos orígenes y sus IDs. |
| E03 | La sesión CMF se atribuye a Strava en contexto y respuesta. |
| E04 | Dos sesiones del mismo día siguen separadas. |
| E05 | La reconsulta actualiza el día sin duplicar y conserva fecha de recogida. |
| E06 | El fallo de un proveedor llega al contexto y los demás datos se conservan. |
| E11 | Consultar el plan no crea versiones, revisiones ni sesiones nuevas. |
| E16 | Medianoche y cambio horario son correctos en API y fallback de Zepp. |
| E17 | La ausencia de Wattwise queda expresada en el contexto. |

Además, el bot debe conservar 81/81 pruebas y el worker debe pasar 151/151 tras
corregir la expectativa de fecha fija. Las cinco pruebas PostgreSQL deben seguir
ejecutándose con PostgreSQL aislado. La línea base de Fase 0 se repite y se
compara sin regresiones en los casos que ya pasaban.

## 7. Migración y despliegue

- Crear una copia de seguridad no destructiva y restaurarla en una base aislada.
- Verificar conteos, relaciones, revisiones, identificadores externos y datos
  históricos antes de aplicar la migración real.
- Orden por cambio: migración aditiva, lector compatible, productor del valor
  nuevo.
- Los datos históricos atribuidos a Garmin no se reescriben. Solo se reclasifican
  si el identificador externo demuestra el proveedor con certeza.
- Cada despliegue debe tener una ruta de vuelta compatible con los datos migrados.
- Verificar con datos sintéticos y lecturas controladas, sin mensajes de prueba
  al usuario ni trabajos reales reclamados.

## 8. Decisiones pendientes

| Decisión | Afecta a | Propuesta |
| --- | --- | --- |
| Nombre de la intención para crear plan | 1.0 | Subcomando explícito, por ejemplo `/plan nuevo`. |
| Reclasificación histórica Garmin/Strava | 1.2 | Solo con identificador externo concluyente. |
| Regla final de coincidencia Garmin/Strava | 1.3 | Partir de la regla candidata y ajustarla con muestra real. |
| ¿Zepp importa actividades o solo bienestar? | 1.3, 1.4 | Decidir con la tabla de cobertura. |
| Vista de estado | 1.4 | Solo lectura; comando definitivo en Fase 4. |
| Exposición del commit remoto | Prerrequisito 1 | Consultar Railway o añadir `/version`. |

## 9. Riesgos

- **Railway no versionado:** puede ejecutar código distinto al auditado. Mitigación:
  SHA visible antes de iniciar cambios.
- **Cobertura desconocida:** se puede confundir proveedor ausente con proveedor
  fallido. Mitigación: tabla de cobertura y estados explícitos.
- **Fusiones erróneas:** una deduplicación agresiva puede unir sesiones distintas.
  Mitigación: ambigüedad visible, tolerancias y casos reales.
- **Cambio horario:** restar horas locales puede perder la hora repetida.
  Mitigación: timestamps absolutos y casos DST en ambas rutas de Zepp.
- **Alcance:** arreglar datos no garantiza una opinión útil. Mitigación: reservar
  la calidad de la respuesta y el enrutamiento para la Fase 2.

## 10. Criterio de cierre

La fase termina cuando todos los casos de la sección 6 pasan, el backup se restaura
correctamente en una base aislada, la compatibilidad API-worker se comprueba con
trabajos pendientes, existe una ruta de vuelta documentada, el commit desplegado
es identificable y el informe recoge explícitamente lo que no se pudo observar.

El cierre de esta fase no certifica todavía que el coach emita una opinión única,
clara y accionable. Esa aceptación pertenece a la Fase 2 y debe incluir casos
basados en los fallos manuales de E01, E07, E08, E09, E10 y E13.
