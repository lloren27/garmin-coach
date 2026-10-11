# Protocolo V2: ámbito explícito

V2 es una capa de seis preguntas sobre el paquete V1, no una edición de V1.
`protocol.json` identifica el sello del manifiesto padre y las sustituciones.
Conserva hechos, relojes, expectativas, mapa, rúbrica, presupuesto y umbral.

SHA-256 de `protocol.json`:
`0801e6871c71d22e442792c817b2f56645b7b73868cd7d42d3c3ec25c9382d91`.

El resolutor reconoce sueño, volumen, comparación retrospectiva y la pregunta de
consejo de E10-mixto. Una frase sin fecha conserva NO_SCOPE; no se asume hoy por
el hecho de que el fixture contenga datos de ese día. Las seis preguntas V2 llevan
«hoy» y consumen el mismo reloj y hechos dentro de cada par.

Preflight determinista desde la raíz:

```sh
apps/sync-local/.venv/bin/python docs/restructuring/fase3_evaluacion/protocol_v2.py
```

Este comando no llama a Ollama ni modifica flags. Comprueba sellos, construye los
15 casos y muestra sus respuestas deterministas. No puntúa automáticamente los
checks: encontrar los códigos esperados no equivale a aprobar todas las exigencias
de calidad. Permanecen los demás límites señalados en la revisión V1.

No hay corrida Ollama V2. El CLI experimental existente sigue siendo V1; no debe
usarse para presentar una corrida como V2. Antes de una comparación nueva será
necesario propagar el identificador y los sellos V2 por generación, exportación
y evaluación, y congelar la implementación de esa corrida. Los resultados V1
conservan sus hashes históricos y no se regeneran con el resolutor modificado.
