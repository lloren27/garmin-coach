---
description: Revisión final en solo lectura de un cambio controlado
agent: orchestrator
---

Revisión final solicitada: $ARGUMENTS
Invoca SOLO a reviewer en primer plano para examinar código real y el diff del archivo previamente aprobado.
Exige referencias a líneas, impacto sobre tests existentes, aserciones añadidas y efectos secundarios.
No invoques local-coder; no modifiques archivos. Emite APROBADO, APROBADO CON OBSERVACIONES o RECHAZADO.
No afirmes que tests pasaron sin salida independiente de `hybrid_guard.py test`.
