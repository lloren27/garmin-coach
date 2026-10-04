# Registro de ejecución — fase 0 v2

Plan: docs/restructuring/restructuring_fase0_v2.md.

- Inicio: 2026-10-03. Referencia de código: b6912b94622d4850cf7b958363ca9551d15f553c.
- Decisión: auditoría sobre el checkout actual, sin editar código del producto, sin rama/commit/despliegue. Los entregables se escriben únicamente en esta carpeta y las pruebas usan almacenamiento temporal. El worker activo apunta a este checkout: no se alterará ningún archivo que carga.
- Topes fijados antes de investigar: traza histórica 10 minutos; cobertura operativa 10 minutos; búsqueda de muestra histórica 5 minutos. Lo no observable se documenta, sin inferir ausencia de actividad.
- Repeticiones: tres para casos con Ollama real; una para deterministas y variantes con dobles.
- 0.1/0.2: en curso. LaunchAgents apuntan a este checkout; no prueba la versión de un proceso ya iniciado.
- Decisión de aislamiento: no llamar GET /ai/jobs/next (reclama trabajos), /status ni /history (loaders PostgreSQL ejecutan ensure_schema). Solo inspección local y, si existe conexión disponible, SELECT en transacción READ ONLY sin importar store.

## Continuación — 4 de octubre de 2026

- Referencia actual: `2abba6ae655c2747fa7d7484cdaf34b323c5955c`. El commit agrega documentos y herramientas de auditoría; `apps/` y `scripts/` no cambian frente a `b6912b9`.
- Backend `/health`: HTTP 200, `ok`. No expone commit. No se reclaman trabajos.
- Ollama accesible con permiso de red local. Se retoman las 18 repeticiones usando el generador real del worker y sus presupuestos según intención, conservando resultados por fecha.
- Correcciones del evaluador: impedir sobrescrituras, comparar también revisión/sesiones en E11, verificar respuesta informativa normal además de rechazo en E15a y no marcar E05/E16 parciales como aprobados globales.
- Pruebas ampliadas: reconsulta Zepp + persistencia pasa; sueño en cambio horario reproduce 480 minutos frente a 540 reales; texto/voz controlada y reserva del worker pasan.
- Suite del bot: 81/81 pasan con PostgreSQL temporal, cero omitidas. Contenedor `garmin-audit-fase0-20261004` retirado tras la suite; no quedan datos de esa base.
- Suite del worker: 150 pasan y 1 falla por expectativa de fecha fija del 29 de septiembre. Se conserva el fallo como evidencia; no se modifica código del producto.
