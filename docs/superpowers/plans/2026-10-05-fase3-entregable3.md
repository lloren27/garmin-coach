# Entregable 3 — Ruta determinista

Implementación autorizada: catálogo admisible tipado y selección con mapa V1,
renderizado común, respuesta por componente y ruta de worker con flag apagado.
Archivos: `coach_findings.py`, `coach_deterministic.py`, asset
`coach_selector_v1.json`, contrato compartido `app/ai_contracts.py` y lector API.

- [x] Catálogo/selección/renderer con referencias, precondiciones y dependencias.
- [x] Mixtas: pedir contexto en E01 y E10; seguridad neutra obligatoria en E10.
- [x] Origen `deterministic` de solo lectura; ampliar lector antes del productor.
- [x] Flag de entorno cargado al inicio; apagado conserva pipeline y alias.
- [x] Pruebas de rechazo, alcance, texto/voz, reserva y regresiones relevantes.

Mapa V1 copiado como asset del paquete: igualdad de bytes verificada en tests.
No importar documentación en runtime. Sin evaluar Ollama ni puntuar el corpus.
Se conservan los límites del resolutor: una paráfrasis sin ámbito se aclara;
no se inventan fechas para hacer pasar un fixture. El catálogo puede probarse
unitariamente con un snapshot de ámbito explícito, separado del experimento.

La ruta V3 de este entregable emite solo information_only/ask_user; el consejo
sin evidencia suficiente pide contexto, y las solicitudes de cambio no aplican
ni proponen cambios desde este selector. No se amplía la generación del modelo.
Una excepción en V3 no debe caer en la reserva prescriptiva legacy: genera una
aclaración determinista segura. Las limitaciones de seguridad no se truncarán.

## Resultado y límites

Catálogo y selección son contratos internos inmutables. El modelo futuro solo
podrá seleccionar IDs existentes: referencia, ámbito, presupuesto, dependencias
obligatorias y seguimiento se validan antes del renderer. Las comparaciones
condicionales conservan la advertencia de identidad; una discrepancia fuera de
banda nunca genera porcentajes. El mapa runtime coincide byte a byte con V1.

API y almacenes validan `deterministic` antes de persistir: solo información o
preguntas, sin deporte/intensidad/dosis prescritos, propuesta ni mezcla de
orígenes. El texto público debe coincidir con el texto estructurado. El lector
de Railway debe desplegarse antes de activar V3 en el worker; los clientes viejos
seguirán enviando sus fuentes anteriores. No se desplegó ni activó nada.

Pruebas: 162 de coach (incluyen 19 nuevas de ruta determinista), 46 de flujo/AI,
6 de completado API, 20 de propuestas y 13 de routing del bot. Las pruebas de
texto/voz simulan entrega y síntesis; no llaman a Telegram, Ollama ni proveedores.
Se revisa además el protocolo V1 sin modificarlo. PostgreSQL real no evaluado;
el guard del almacén PostgreSQL se comparte con el contrato validado.

Limitación concreta: la frase congelada de E10-mixto «dime: ¿hago la sesión…?»
produce un segundo componente CLARIFY sin fecha con el resolutor actual. V3
mantiene esa aclaración y la limitación de seguridad, sin inventar ámbito.
La variante reconocida «dime qué hacer mañana» prueba dos fechas/componentes.
Esto no certifica que E10-mixto cumpla todas sus expectativas: debe reportarse
en la evaluación y resolverse antes del cierre global si se exige fecha futura.
Tampoco se certifica calidad de respuestas ni E14 global: los alias locales
siguen como antes; su migración no forma parte de este entregable.

Revisión local; no se ha realizado revisión independiente ni experimento ciego.
