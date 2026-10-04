# Informe de auditoría — Fase 0

Fecha de ejecución: 3 de octubre de 2026. Checkout auditado: `b6912b94622d4850cf7b958363ca9551d15f553c` (`main`).

## Alcance y aislamiento

La referencia y los artefactos están en esta carpeta. Las pruebas se ejecutaron
con datos sintéticos, almacenamiento temporal y dobles para Telegram. La guardia
del evaluador bloqueó escrituras fuera del área temporal, lectura de secretos y
redes distintas de la eventual conexión local a Ollama. No se ejecutaron el
worker normal, la sincronización ni trabajos de Telegram.

La inspección local verificó que los LaunchAgents apuntan al checkout actual:
worker cada 60 segundos, sincronización cada 4 horas y en horarios configurados,
y watcher de solicitudes cada 5 minutos. Los logs locales contienen ejecuciones
de sincronización entre el 2 de septiembre y el 3 de octubre, pero no prueban
por sí solos el éxito individual de Garmin, Strava y Zepp. El fichero de
configuración local no se exportó; los valores saneados y hashes están en
`referencia.json`.

Railway no se pudo versionar de forma segura en esta auditoría: no hay CLI
disponible y no se llamaron endpoints que puedan preparar esquema o reclamar
trabajos. Queda como `no observable`.

## Línea base determinista

| Caso | Resultado | Evidencia principal |
| --- | --- | --- |
| E02 | Incumple | `activity_merge` devuelve una actividad, pero no conserva una relación explícita con ambos registros; el comprobador no puede acreditar ambos orígenes. |
| E03 | Incumple | `build_snapshot` normaliza una actividad con `source=strava` a `garmin` porque no admite Strava como origen. |
| E04 | Cumple | Dos actividades separadas no se fusionan por fecha. |
| E05 | Cumple parcial | El almacén local actualiza el mismo día y fuente sin duplicar. La reconsulta real a Zepp no se ejecutó. |
| E06 | Incumple | El estado de error del proveedor no llega como evidencia utilizable al contexto validado. |
| E11 | Incumple | `/plan` vuelve a construir y guardar el plan al consultarlo; la evaluación observó identificadores distintos. |
| E12 | No evaluable | El contrato interno prohíbe `answer`; se verifican rechazo estructural y reparación, pero no contradicción semántica entre explicación y decisión. |
| E14 | Incumple | Texto y `/coach` crean trabajo IA, la voz también; `/feedback` se resuelve directamente y usa otro camino. |
| E15a | Cumple parcial | Una propuesta no autorizada se rechaza y no escribe. Falta comprobar que la recomendación informativa se conserve como respuesta completada. |
| E15b | Cumple | La propuesta autorizada queda pendiente y el plan no cambia en almacenamiento local. PostgreSQL no se evaluó. |
| E16 | Cumple parcial | El normalizador Strava asigna las fechas esperadas en los timestamps comprobados. El sueño Zepp y su deduplicación no se ejecutaron. |
| E17 | Incumple | El contexto no conserva de forma suficiente la indisponibilidad de Wattwise para que el entrenador la explique. |

Los resultados completos por ejecución están en `ejecuciones/`. Los casos E01,
E07, E08, E09, E10 y E13 requieren Ollama real y no forman parte de esta tabla.

## Ollama

Se prepararon tres repeticiones por caso de entrenador. El evaluador se corrigió
para usar los mismos parámetros estructurados que el worker: temperatura 0,
`top_p=0,9`, `top_k=20`, contexto 32.768 y el límite de tokens correspondiente.
La ejecución dentro del entorno restringido no pudo abrir `127.0.0.1:11434`;
las 18 repeticiones quedaron como `no evaluable` con `ConnectError`. Las primeras
ejecuciones exploratorias usaban parámetros distintos y no se consideran línea
base válida.

Para cerrar la parte de Ollama hace falta ejecutar el mismo evaluador desde un
entorno con acceso al servicio local. Debe conservar las tres respuestas, las
reparaciones y la latencia de cada repetición. Un error del propio evaluador se
clasifica como `no evaluable`, nunca como fallo del producto.

## Pruebas existentes

- Bot: 81 pruebas ejecutadas, 0 fallos, 5 omitidas por depender de PostgreSQL aislado.
- Worker: 151 pruebas ejecutadas, 1 fallo y 0 errores. El fallo es
  `test_build_payload_imports_strava_activity_from_sixty_day_window`, que espera
  una ventana fija de septiembre y el código calcula la ventana desde la fecha
  actual del checkout. El error está documentado; no se ha modificado el producto.

Estas suites son regresiones del repositorio, no sustituyen los 17 casos de esta
fase.

## Hallazgos priorizados

### P1

- El contexto validado pierde `source=strava`, por lo que una sesión CMF puede
  atribuirse a Garmin.
- La experiencia no tiene entrenador único: `/feedback`, `/semana`, `/proximo`
  y otras consultas mantienen rutas deterministas separadas de `/coach`.
- `/plan` consulta y persiste un plan nuevo, mezclando lectura con escritura.

### P2

- El estado y la frescura de los fallos de proveedor no están representados de
  forma suficiente en el contexto del entrenador.
- El flujo de propuesta no autorizado protege la persistencia, pero todavía no
  se ha verificado que preserve una respuesta informativa.
- La deduplicación devuelve un registro principal sin un vínculo explícito y
  auditable con todos los orígenes relacionados.
- Wattwise ausente no queda expresado de manera suficiente para una respuesta útil.

### P3

- Parte de la documentación y del README describe una unificación que el
  enrutador aún no implementa.
- Hay contratos y rutas de generación paralelos (`ai_contracts`, contrato interno
  validado y la ruta antigua de validación), cuya relación debe aclararse antes
  de extraer módulos.

## Limitaciones y cierre

La fase 0 no permite afirmar todavía cómo valora Ollama el caso E01 ni medir la
calidad de sus recomendaciones, porque el servicio no fue accesible desde el
entorno de ejecución. Tampoco permite comprobar Railway, PostgreSQL, la
reconsulta real de proveedores ni el comportamiento durante suspensión del Mac.

La auditoría está cerrada para las partes deterministas y queda **parcialmente
cerrada** para la línea base completa: aislamiento, inventario, traza sintética,
cobertura local y hallazgos están documentados; la ejecución de Ollama y las
lecturas remotas permanecen `no evaluable` por limitación de entorno. No se debe
presentar esta fase como completa hasta repetir Ollama desde un entorno con acceso
local y decidir si se necesita una lectura remota explícita para cubrir Railway.

La Fase 1 puede planificarse ya para corregir procedencia, separar lectura y
escritura del plan y unificar el enrutamiento, pero su línea base de calidad del
entrenador debe incorporar primero las repeticiones válidas de Ollama.
