# Ejecución — restructuring_fase1_v1.md

Base: d7f2293fe176793c65e83994186d4fdbbaeff610. Rama codex/fase1, worktree .worktrees/fase1.

- Línea base: worker 152 pruebas, 151 pasan y falla la expectativa Strava fuera del reloj simulado. No errores ni accesos externos.
- Decisión: la implementación y sus pruebas aisladas pueden avanzar sin certificar Railway; la verificación del SHA remoto es un requisito de despliegue/cierre, no motivo para detener cambios locales.
- Decisión: usar `/plan nuevo` (también `/plan_semana nuevo`) para creación explícita. Consultar no crea ni sustituye planes.
- Decisión: no reclasificar históricos. Añadir metadatos de origen al JSON existente sin modificar tablas; verificar persistencia y restauración aisladas. La restauración de copia real requiere evidencia propia y no se dará por hecha con datos sintéticos.
- Decisión: conservar importación Zepp existente; no cambiar preferencias del usuario durante una corrección de coherencia.
- Dependencias: 1.2/1.3 comparten metadatos de actividad; 1.4/1.5 comparten estado por proveedor. Mantener contratos aditivos y compatibles con documentos antiguos.

## Tareas

- [x] 1.1 Reloj y fechas de pruebas. `worker 161/161` en `fase1-green3`.
- [x] 1.0 Consulta del plan sin escritura. `bot 85/85` en `fase1-green3`.
- [x] 1.2 Procedencia y dispositivo, incluido `/version` con SHA validado.
- [x] 1.3 Vínculos de deduplicación; las coincidencias ambiguas y las fusiones no uno-a-uno permanecen visibles.
- [x] 1.4 Estado y frescura por proveedor, con último intento/éxito, periodo y error acotado.
- [x] 1.5 Wattwise no disponible; su estado se conserva aunque falten credenciales o falle el servicio.
- [x] 1.6 Sueño y cambio horario en API directa y fallback de banda; E16 ampliado pasa.
- [x] Persistencia aditiva verificada en JSON y en PostgreSQL desechable (`bot 85/85`, con seis pruebas PostgreSQL).

## Evidencia y límites de cierre

La aceptación determinista se repitió en `fase1-aceptacion1`: E02, E03, E04,
E06, E11 y E17 pasan. Las pruebas ampliadas `fase1-ampliadas1` pasan para la
reconsulta tardía de Zepp, el cambio horario y el contexto extremo a extremo.
E05 y E16 aparecen como no evaluables en el evaluador histórico porque sus
casos originales no incluyen PostgreSQL ni sueño Zepp; sus comprobaciones
específicas sí están cubiertas por las pruebas ampliadas. E14 continúa fuera de
esta fase y corresponde a la unificación de enrutamiento de Fase 2.

| Proveedor | Cobertura confirmada en esta fase | Límite |
| --- | --- | --- |
| Garmin Instinct / Edge 530 | Normalización, fallo aislado, estado y pruebas sintéticas | No se reconsultó una cuenta real durante esta ejecución |
| Strava desde CMF | Procedencia, dispositivo, ventana y deduplicación sintéticas | No se certifica conectividad real del teléfono |
| Zepp Helio Strap | Sueño directo, fallback de banda, fechas y DST europeo | No se cubren todas las variantes de sueño de la API |
| Wattwise | Ausente, no configurado, error y periodo en contexto | No se certifica disponibilidad remota en esta ejecución |

El PostgreSQL temporal se creó para pruebas y se destruye al terminar; la
persistencia se comprobó, pero todavía no se ha restaurado una copia real de
producción. La restauración real y la comparación con el despliegue Railway
requieren una copia `.dump`/`.sql` y el SHA remoto; no se simulan como si
estuvieran verificadas.

El 4 de octubre se recibió `backup-audit/garmin-coach-production.dump`. La
validación local del archivo pasó: formato custom PostgreSQL, 850 KB, SHA-256
`ebb6fa4995f381e9c40255b68b89e9eb32fd5acf1b6be84194c5ef945b2ec61`, 46 entradas,
esquema generable y datos legibles. El contenido incluye 8 tablas: 53 trabajos
de coach, 1 check-in, 0 cambios pendientes, 25 sesiones planificadas, 857
registros de historial de sincronización, 7 claves de estado, 3 planes y 45
registros diarios de bienestar. La restauración en PostgreSQL aislado queda
pendiente porque Docker no está accesible desde este entorno; el backup no se
restauró sobre producción.
