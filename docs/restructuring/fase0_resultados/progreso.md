# Registro de ejecución — fase 0 v2

Plan: docs/restructuring/restructuring_fase0_v2.md.

- Inicio: 2026-10-03. Referencia de código: b6912b94622d4850cf7b958363ca9551d15f553c.
- Decisión: auditoría sobre el checkout actual, sin editar código del producto, sin rama/commit/despliegue. Los entregables se escriben únicamente en esta carpeta y las pruebas usan almacenamiento temporal. El worker activo apunta a este checkout: no se alterará ningún archivo que carga.
- Topes fijados antes de investigar: traza histórica 10 minutos; cobertura operativa 10 minutos; búsqueda de muestra histórica 5 minutos. Lo no observable se documenta, sin inferir ausencia de actividad.
- Repeticiones: tres para casos con Ollama real; una para deterministas y variantes con dobles.
- 0.1/0.2: en curso. LaunchAgents apuntan a este checkout; no prueba la versión de un proceso ya iniciado.
- Decisión de aislamiento: no llamar GET /ai/jobs/next (reclama trabajos), /status ni /history (loaders PostgreSQL ejecutan ensure_schema). Solo inspección local y, si existe conexión disponible, SELECT en transacción READ ONLY sin importar store.
