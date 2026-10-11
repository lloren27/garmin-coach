# Diagnóstico de las aclaraciones en la evaluación V1

## Resultado

Las seis preguntas contrastadas fallan antes de la selección de hallazgos.
Con sus preguntas y relojes originales, cada una produce un componente CLARIFY,
cero hechos analíticos y cero hallazgos admisibles. Por ello, las salidas válidas
de Ollama en esos casos no demuestran una buena selección: el catálogo está vacío.

| Casos | Resolución original | Causa |
| --- | --- | --- |
| E01-pace, R01-pace | unsupported_paraphrase | «qué tal» solo activa análisis si ya hay una fecha retrospectiva explícita. |
| E01-volume | unsupported_paraphrase | «cumplí el volumen» no figura entre las señales retrospectivas reconocidas. |
| E01-sleep | unsupported_paraphrase | «cómo dormí» no figura entre las señales retrospectivas reconocidas. |
| E01-plan, R01-distance | no_scope | La palabra «plan» dirige a CONSULT_PLAN; la pregunta no contiene fecha. |

`coach_intent.py` resuelve usando únicamente pregunta y reloj. No recibe la
actividad seleccionada ni un ámbito conversacional. `coach_analysis.py` excluye
evidencias sin ámbito observado resuelto. Esa barrera evita inventar fechas.

## Comprobaciones aisladas, sin generar respuestas de Ollama

Se ejecutó el resolutor sobre las frases originales y sobre variantes únicamente
en memoria. No se editaron V1 ni los resultados anteriores.

- Añadir «hoy» resuelve las preguntas de ritmo como ANALYZE_DAY.
- Añadir «hoy» no reconoce «cumplí el volumen» ni «cómo dormí».
- Añadir «hoy» a las comparaciones con el plan produce CONSULT_PLAN con fecha
  de consejo; sigue sin representar el análisis retrospectivo esperado.
- Anteponer «Analiza hoy:» a las seis frases produce ANALYZE_DAY con fecha
  2026-10-03 y permite construir hechos y hallazgos no vacíos.

Esto identifica dos fallos de reconocimiento y un desacuerdo entre las preguntas
sin ámbito de V1 y sus expectativas de análisis fechado. No hay evidencia de que
Ollama cause esa pérdida de ámbito.

## E10-mixto

La división en dos componentes funciona. El primero analiza hoy; el segundo,
«dime: ¿hago la sesión de umbral de mañana?», devuelve unsupported_paraphrase.
«Mañana» es una fecha reconocible, pero la forma interrogativa «¿hago la sesión…?»
no coincide con la señal de recomendación. La forma «dime qué hago mañana» sí
reconoce consejo futuro. La corrección corresponde a reconocimiento de intención,
sin convertir una pregunta en permiso de cambio o aprobación de la sesión.

## Corrección propuesta

1. Ampliar de forma acotada las señales analíticas para sueño, volumen y
   comparación retrospectiva con el plan. La comparación debe preceder a la regla
   genérica de CONSULT_PLAN. Cubrir negaciones, futuras consultas y solicitudes
   de cambio para no ampliar permisos accidentalmente.
2. Reconocer la pregunta «¿hago la sesión de … mañana?» como RECOMMEND_NEXT,
   manteniendo las fechas por componente y las barreras de síntomas. No autoriza
   keep_plan, prescripción, propuesta ni mutación en E10-mixto.
3. Conservar NO_SCOPE cuando realmente falta fecha/actividad. No asumir hoy ni
   la última actividad a partir del fixture. Para evaluar selección, registrar
   antes de generar un protocolo V2 con preguntas de ámbito explícito, idéntico
   dentro de cada par. Una alternativa futura es un contrato explícito de ámbito
   conversacional, pero requiere diseño adicional y no es necesario para este
   arreglo acotado.
4. Verificar la ruta determinista con las frases reconocidas, los casos mixtos y
   regresiones de autoridad/fecha. No repetir Ollama mientras persistan fallos de
   cobertura previos al selector. Conservar V1 como evidencia de la limitación.

## Alcance de este trabajo

Solo diagnóstico y propuesta: no se modificó código de producto, protocolo,
resultados, permisos o configuración. La corrida anterior no justifica integrar
Ollama, pero tampoco prueba superioridad del selector sobre entradas que llegaron
sin hechos. La revisión asistida anterior no fue completamente ciega.

## Implementación posterior autorizada

Tras aprobar el diagnóstico, se añadieron señales acotadas al resolutor para las
preguntas descritas. Las preguntas sin ámbito devuelven NO_SCOPE, las de análisis
retrospectivo con fechas futuras se aclaran, y las formas declarativas o negadas
probadas no se convierten en consejo. E10-mixto conserva la fecha futura y solo
pide contexto, sin propuesta ni aval de seguridad.

V2 se preparó como capa versionada sobre V1 en `v2/protocol.json`, con seis
preguntas que incluyen «hoy». `protocol_v2.py` verifica sellos y prepara las
respuestas deterministas. Los seis casos tienen hechos y códigos requeridos;
los hechos y relojes de cada par permanecen iguales. No se ejecutó Ollama.

Verificación: 281 pruebas del worker y 29 del protocolo/arnés, sin fallos.
El sello del manifiesto V1 permanece
`cd43210d439c25d7a8bf93579ce936d83b116ffead42fe78d2698e71fa84caf0`.
El CLI Ollama existente no acepta aún V2; su conexión futura se documenta en
`v2/README.md`. No se presenta este preflight como evaluación global ni cierre.
