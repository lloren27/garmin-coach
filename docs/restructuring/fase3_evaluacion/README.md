# Fase 3 — Protocolo previo a generación, V1

Entregable 1 terminado: fixtures, expectativas, mapa de foco y rúbrica fijados.
No se ha generado, seleccionado ni puntuado ninguna respuesta del coach.

Sello SHA-256 de `v1/manifest.json`:

```text
cd43210d439c25d7a8bf93579ce936d83b116ffead42fe78d2698e71fa84caf0
```

El manifiesto contiene hashes de los cuatro archivos de contrato y de las 18
fuentes originales E01–E17 (E15a/b). Este sello permite detectar cambios; no es
almacenamiento inmutable. El verificador no actualiza hashes. Comparar también
el sello publicado antes de evaluar. Después de esta entrega, cualquier ajuste
de preguntas, entradas, mapa, expectativas, presupuestos o umbral crea V2 y una
corrida nueva, conservando V1. No recalibrar V1 después de ver respuestas.

## Contenido

| Archivo | Contrato congelado |
| --- | --- |
| `v1/fixtures.json` | Copias íntegras de E01–E17, R01 adicional y variantes materializables. |
| `v1/expectations.json` | Expectativas de los 32 casos; códigos requeridos/prohibidos, acciones, hechos numéricos y límites de cobertura. Todos `not_run`. |
| `v1/selector_map.json` | Normalización, frases por familia, orden, presupuesto, dependencias obligatorias y conducta sin foco. |
| `v1/rubric.json` | F/P/U/R 0–2, revisión ciega, seis victorias requeridas, empate para selector, controles y límites del experimento. |
| `v1/manifest.json` | Hashes de contrato y originales. |

Los 32 casos son 18 originales, R01, seis preguntas contrastadas, dos mixtos y
cinco variantes de correspondencia (confirmada, calentamiento, varias parejas,
datos insuficientes y dentro de rango). E01 permanece íntegro. Las variantes
heredan reloj con zona horaria y hechos de su base, cambian la pregunta y aplican
solo reemplazos de entrada expresos. Los contrastes no permiten reemplazos:
ambas preguntas de cada par comparten exactamente hechos y reloj.

Los originales conservan sus campos históricos `debe` y `modo_modelo`; las
expectativas de V1 son las de `expectations.json`. Las discrepancias deliberadas
de alcance están identificadas: E14 se informa parcial porque los alias reales
siguen locales; E12 requiere integración de reparación solo si gana Ollama.
E10 no se trata como un análisis puro: su pregunta sobre la sesión futura activa
la limitación de seguridad y pide contexto. E15a/b conservan criterios de
autorización y persistencia, cuya ejecución queda pendiente.

## Comparación fijada

| Par | Hechos | Preguntas |
| --- | --- | --- |
| `pair-e01-pace-volume` | E01 | Ritmo / cumplimiento de volumen |
| `pair-e01-sleep-plan` | E01 | Sueño / diferencia frente al plan |
| `pair-r01-pace-distance` | R01 | Ritmo / diferencia de distancia |

La evaluación de calidad principal utiliza V3 y enforcement encendidos. Ambas
selecciones reciben los mismos hechos, pregunta, presupuesto y renderer. El
selector usa el mapa de foco congelado. Ollama debe superar su U en las seis
preguntas sin retroceder en F/P/R, pasar expectativas y superar controles de
seguridad; un empate basta para conservar la ruta determinista como principal.
Los siete casos base de respuesta y los dos mixtos son controles adicionales.
No se excluyen casos desfavorables tras ejecutar.

Se puntúa con identificadores opacos y orden aleatorio; origen y datos de
ejecución quedan ocultos hasta cerrar puntuaciones. Quienes escriben expectativas
y quienes puntúan pueden ser las mismas personas: la revisión ciega no elimina
ese sesgo. Los dos pares de E01 tampoco son muestras independientes.

El arnés de modelo se construirá en el entregable 4. Antes se implementan hechos,
selector determinista y renderer. Este paquete no llama al evaluador de Fase 0,
que ejecutaría producto y podría generar resultados. Los presupuestos se fijan
a partir de los defaults del worker, sin leer secretos: modelo `garmin-coach:9b`,
900 tokens de análisis, 1400 de plan, 600 s. La configuración efectiva y el digest
se comprobarán antes de la corrida; diferencias requieren versión nueva previa.

## Verificación del entregable

Desde la raíz:

```sh
apps/sync-local/.venv/bin/python docs/restructuring/fase3_evaluacion/verify_protocol.py
apps/sync-local/.venv/bin/python -m unittest discover -s docs/restructuring/fase3_evaluacion -p 'test_protocol.py' -v
shasum -a 256 docs/restructuring/fase3_evaluacion/v1/manifest.json
```

Resultado de esta entrega: verificador sin errores; 12 pruebas del contrato pasan.
Se comprueba deriva de bytes, JSON roto, cobertura de casos, identidad de los
hechos en pares, expectativas de seguridad, desempate, reloj zonificado,
materialización sin mutar la base, mapa de foco y cifras de referencia.

No se han ejecutado las suites de bot/worker, E15 en persistencia ni PostgreSQL;
quedan **no evaluados en este entregable**. Las pruebas de este paquete verifican
la integridad del criterio, no certifican todavía el comportamiento del producto.
No se han modificado flags, alias ni configuración de servicios.
