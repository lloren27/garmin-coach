# Fase 3 — Entregable 1: protocolo congelado

> **For agentic workers:** ejecución nativa autorizada por el usuario para este
> entregable; seguir los pasos y registrar su verificación aquí.

**Goal:** congelar entradas y criterios antes de generar o puntuar respuestas.

**Architecture:** paquete JSON V1 autocontenido, con copias de los fixtures de
Fase 0, variantes identificadas, expectativas por caso, mapa de foco y rúbrica.
Un manifiesto SHA-256 y un verificador de solo lectura detectan deriva. La ruta
del producto y el evaluador que llama a Ollama no se ejecutan.

**Tech Stack:** JSON, Python estándar en `apps/sync-local/.venv/bin/python`.

**Spec:** `docs/superpowers/specs/2026-10-04-fase3-coach-analysis-design.md`.

## Global Constraints

- Solo entregable 1; no implementar selector ni generador ni activar flags.
- E01 original intacto; R01 adicional; seis preguntas contrastadas sobre dos fixtures.
- E10-mixto exige limitación de seguridad y aclaración; prohíbe `keep_plan`.
- Empate para selector; mapa/preguntas/expectativas/rúbrica congelados previamente.
- E14 parcial; PostgreSQL y suites de producto no evaluados en este entregable.

## Review Focus

- Deriva de bytes tras congelar: verificador debe rechazarla.
- Pares con hechos distintos: comparar entradas y reloj con el fixture base.
- Fuentes originales alteradas: verificar copia y hash de origen.
- Desenlace mixto permisivo: exigir aclaración y lista de acciones prohibidas.
- Congelación sin cobertura: exigir E01–E17, E15a/b, R01 y variantes.

## Tarea única: contrato previo a evaluación

Archivos: `docs/restructuring/fase3_evaluacion/v1/{fixtures,expectations,selector_map,rubric,manifest}.json`,
`docs/restructuring/fase3_evaluacion/{README.md,verify_protocol.py,test_protocol.py}`.

Interfaz: `verify_protocol.verify(directory: Path) -> list[str]`, solo lectura;
CLI devuelve 0 con paquete íntegro y 1 si existe deriva o contrato inválido.

- [x] Crear fixtures autocontenidos, preguntas, valores esperados y cobertura.
- [x] Especificar algoritmo del mapa de foco y rúbrica ciega, con desempate.
- [x] Probar rechazo de deriva, pares distintos y expectativas mixtas inválidas.
- [x] Completar verificador y sellar el manifiesto final antes de generar.
- [x] Revisar coherencia y documentar pruebas; no generar resultados del coach.

Verificación: 12 pruebas verdes y verificador sin errores. Se observó inicialmente
fallo por ausencia del verificador; al agregar el caso confirmado se corrigió un
test que identificaba variantes por posición, para localizarlas por ID estable.
R01 usa `distance_km` en sesiones según el contrato actual. La revisión fue local;
no se ha obtenido una revisión independiente ni se han evaluado respuestas.

La congelación se identifica por el SHA-256 del manifiesto comunicado al usuario.
Cambios posteriores crean V2 y una nueva corrida. No se hace commit/merge/push
como parte de este entregable.
