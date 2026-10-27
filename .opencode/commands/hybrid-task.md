---
description: Tarea híbrida secuencial con aprobación humana y Hybrid Guard
agent: orchestrator
model: opencode/nemotron-3.5-super-vl-free
---

TAREA SOLICITADA: $ARGUMENTS

Flujo obligatorio, secuencial y supervisado:

1. El usuario prepara una tarea activa con `.opencode/scripts/hybrid_guard.py begin`, declara las rutas exactas permitidas y el perfil de tests. No inicies `local-coder` sin tarea activa.
2. Invoca `explorer` en primer plano y solo lectura para inspeccionar el código relacionado y proponer un cambio mínimo.
3. Como `orchestrator`, resume la propuesta, el archivo exacto autorizado y sus criterios de aceptación. Espera aprobación explícita del usuario antes de invocar `local-coder`.
4. Tras la aprobación, invoca `local-coder` en primer plano. Toda escritura de Qwen debe hacerse exclusivamente con `hybrid_guard_write`, sobre una ruta incluida literalmente en el manifiesto y con la aprobación humana nativa de OpenCode. Nunca sugieras `edit`, `write`, `apply_patch`, shell ni otra alternativa para escribir. Si la herramienta no está disponible o el permiso se deniega, detente.
5. Cuando Qwen termine, invoca `reviewer` en primer plano para revisar el cambio real y emitir un veredicto explícito. El Reviewer es remoto, de solo lectura, y no puede ejecutar herramientas ni modificar archivos.
6. Cuando la sesión supervisada de OpenCode haya terminado, el usuario inspecciona el estado con `launch-review` y confirma esa revisión humana con `ack-launch`. Después ejecuta `check`, `test` y, si todo es correcto, `finalize`. No declares completado el flujo antes del veredicto del Reviewer y de la validación del guard.

No apruebes permisos en nombre del usuario. No uses `--auto`, no ejecutes agentes en segundo plano y no hagas commit, push o merge. No leas credenciales, secretos, `.env`, bases de datos ni datos de producción. Conserva todas las restricciones configuradas de `local-coder` y el alcance exacto de escritura del guard.
