# Diseño: integración Zepp / Amazfit Helio Strap

## Objetivo

Incorporar los datos diarios de salud recogidos por la Helio Strap a Garmin
Coach. Zepp será la fuente preferida cuando una métrica de bienestar sea
comparable y válida; Garmin permanecerá como la fuente de actividades y de
fisiología deportiva de referencia. La solución debe conservar el valor y la
procedencia de cada señal para que el bot, Ollama y la depuración nunca
confundan métricas de proveedores distintos.

## Alcance

El sincronizador local instalará e importará `zepp-export` como librería Python
y usará `ZeppClient` con `ZEPP_TOKEN`, `ZEPP_USER_ID` y `ZEPP_BASE_URL`. No se
enviarán credenciales Zepp a Railway. Cada sincronización consultará el día en
curso y los `ZEPP_SYNC_LOOKBACK_DAYS` anteriores; el valor por defecto será `2`,
por lo que se consultarán hoy, ayer y anteayer. Esto captura consolidaciones de
sueño, sincronizaciones tardías de la pulsera y correcciones realizadas en la
app Zepp.

El cambio se limita a wellness. Las actividades, resúmenes de carrera y
analítica de Wattwise se mantendrán exclusivamente desde Garmin.

## Arquitectura y contrato de datos

Se añadirán tres unidades independientes al paquete `garmin_sync`:

- `ZeppProvider`: adapta `ZeppClient`, clasifica los errores de credenciales,
  red y respuestas inválidas, y obtiene datos para el intervalo de días.
- Normalizador Zepp: convierte las respuestas externas a un contrato interno
  diario, sin filtrar ni mezclar valores Garmin.
- `WellnessResolver`: aplica una política determinista por métrica o grupo y
  produce la vista que consumen el bot y Ollama.

El payload conservará las fuentes y la vista resuelta:

```json
{
  "wellness": {
    "schema_version": 2,
    "garmin": { "2026-09-22": {} },
    "zepp": { "2026-09-20": {}, "2026-09-21": {}, "2026-09-22": {} },
    "effective": {
      "date": "2026-09-22",
      "resting_hr": { "value": 47, "unit": "bpm", "source": "zepp", "observed_at": "2026-09-22" },
      "steps": { "value": 8231, "unit": "steps", "source": "zepp" },
      "sleep": { "source": "zepp", "total_minutes": 448, "deep_minutes": 82 }
    },
    "history": {
      "2026-09-20": { "effective": {} },
      "2026-09-21": { "effective": {} },
      "2026-09-22": { "effective": {} }
    },
    "provider_status": {
      "zepp": {
        "status": "ok",
        "last_success_at": "2026-09-22T20:02:31+02:00",
        "days_requested": 3,
        "days_received": 3
      }
    }
  }
}
```

`wellness.effective` siempre representa hoy; `wellness.history` contiene las
vistas resueltas de los días reconsultados. `schema_version: 2` permite a los
consumidores detectar explícitamente el nuevo contrato. Las claves existentes del wellness
Garmin se preservarán dentro de `wellness.garmin` para no perder trazabilidad.
Los formateadores y el contexto de IA migrarán a la vista effective y mostrarán
la fuente cuando comuniquen una métrica.

## Política de precedencia

No se aplicará una regla global de mezcla. La política será una constante
documentada y testeada:

```python
EFFECTIVE_SOURCE_POLICY = {
    "sleep": ("zepp", "garmin"),
    "resting_hr": ("zepp", "garmin"),
    "steps": ("zepp", "garmin"),
    "stress": ("zepp",),
    "atl": ("zepp",),
    "ctl": ("zepp",),
    "tsb": ("zepp",),
    "trimp": ("zepp",),
    "sport_load": ("zepp",),
    "vo2max": ("garmin",),
}
```

La política sólo ordena candidatos; no convierte un valor presente en uno
válido. El resolver dispondrá de validadores defensivos por métrica. Como
mínimo, FC de reposo debe estar entre 20 y 250 bpm, pasos admite cero, sueño y
VO2max deben ser positivos, TRIMP no puede ser negativo y ATL/CTL/TSB requieren
un valor numérico. Un candidato inválido se descarta antes de intentar la
siguiente fuente que permita la política. El resultado efectivo conserva
`value`, `unit`, `source` y `observed_at` siempre que el origen lo aporte.

Una métrica con una sola fuente no obtendrá un sustituto con el mismo nombre
desde otro proveedor. El payload de origen seguirá reteniendo ambas, por
ejemplo `physiology.max_metrics.vo2max_running` de Garmin y `wellness.zepp`
para el VO2max calculado por Zepp. Ninguna de ellas se sobrescribirá ni se
presentará como si midiera exactamente lo mismo.

## Sueño atómico

El sueño es un bloque indivisible. Una sesión pertenece a la fecha local en la
que termina, no a la fecha en que empieza. `WellnessResolver` elegirá la primera sesión
completa válida según `sleep: (zepp, garmin)`: debe incluir una duración total
positiva y no contradecir las fases disponibles. Todas las fases y la
puntuación de `effective.sleep` provendrán de esa misma fuente. Si Zepp no
proporciona una sesión completa, se seleccionará la sesión Garmin completa;
nunca se combinarán minutos o fases de ambos dispositivos. El proveedor usará
`get_sleep()` de zepp-export, que ya contempla sesiones que cruzan medianoche.
El normalizador deduplicará la misma sesión por su identificador, o por
`start`/`end` cuando no exista, durante el lookback. La sesión elegida retendrá
sus timestamps de inicio y fin.

## Normalización Zepp

Por cada día solicitado, el proveedor recogerá las señales disponibles:

- sueño completo, puntuación y FC en reposo;
- pasos y segmentos de actividad;
- estrés a cinco minutos, con resumen diario derivado;
- carga: ATL, CTL, TSB, TRIMP y sport load;
- VO2max de Zepp como observación auxiliar por entrenamiento, separada del
  VO2max Garmin y con su `observed_at` real.

Los datos minuto a minuto o a cinco minutos se resumirán para el payload de
coaching; no se enviarán series completas a Railway salvo que un futuro caso de
uso lo requiera. El resumen de estrés incluirá `avg`, `min`, `max`,
`sample_count`, `coverage_minutes` y, si la respuesta lo permite, minutos por
zona (`low_minutes`, `medium_minutes`, `high_minutes`). Así el coach puede
interpretar la calidad de cobertura y no sólo un promedio. Se conservarán los
agregados, fecha y fuente, manteniendo el payload compacto.

El VO2max Zepp no se generará artificialmente para cada día del lookback: una
fecha sin entrenamiento cualificado significa «sin nueva observación», no un
valor nulo de VO2max. Permanecerá en el origen Zepp para auditoría y no entrará
en `effective.vo2max`, que continúa siguiendo la referencia deportiva Garmin.

## Resiliencia y seguridad

La falta de configuración Zepp desactiva el proveedor sin afectar Garmin. Un
token caducado se identifica como `auth_error`, se informa en
`provider_status.zepp` sin incluir el token y permite el fallback únicamente
para las métricas que lo declaren. Fallos de red, API o datos parciales se
aislarán igual. La sincronización Garmin y el POST al backend continuarán.

`provider_status.zepp.status` será uno de `ok`, `partial`, `disabled`,
`auth_error`, `network_error`, `api_error` o `invalid_data`. El contrato
incluye `last_success_at`, `days_requested` y `days_received`; por ejemplo,
`partial` con 3 y 2 comunica un resultado usable pero incompleto. La capa de
aislamiento es deliberada porque Zepp-export usa una API no oficial que puede
cambiar.

`ZEPP_TOKEN` no se imprimirá, persistirá ni enviará a Railway. Se documentarán
`ZEPP_TOKEN`, `ZEPP_USER_ID`, `ZEPP_BASE_URL` y
`ZEPP_SYNC_LOOKBACK_DAYS=2` en `.env.example` y README, junto con el paso de
instalación local.

## Persistencia y resync

La API no tratará el lookback como un mero reemplazo del wellness actual. Cada
instantánea diaria se guardará mediante upsert por `user_id`, `wellness_date` y
`source`, con una restricción única equivalente a
`UNIQUE(user_id, wellness_date, source)`. Una sincronización posterior de Zepp
actualizará esa fila y reconstruirá la vista efectiva de esa fecha, en lugar de
crear duplicados. El almacenamiento sin Postgres mantendrá la misma semántica
mediante un índice determinista por fecha y fuente. Así una consolidación de
sueño tardía modifica el día correcto y el lookback cumple su propósito.

## Presentación y contexto de coaching

`/today`, `/health` y el contexto que se entrega a Ollama leerán
`wellness.effective`. Las líneas que contengan señales de wellness incluirán
la procedencia, por ejemplo `Sueño: 7h28 [Zepp]` y `FC reposo: 47 bpm [Zepp]`.
Los valores deportivos Garmin seguirán etiquetados como Garmin. Si una fuente
no está disponible, la salida explicará el dato real disponible sin inventar
equivalencias ni mostrar el secreto o el detalle técnico del error.

## Pruebas y criterios de aceptación

La integración contará con pruebas aisladas para:

1. normalización de respuestas Zepp;
2. precedencia por métrica Zepp/Garmin;
3. fallback Garmin sólo donde la política lo autoriza;
4. caída completa de Zepp sin bloquear el sync Garmin;
5. token Zepp caducado clasificado sin filtrar secretos;
6. datos Zepp parciales;
7. selección atómica de una sesión de sueño;
8. ausencia de mezcla automática de métricas no equivalentes;
9. re-sincronización y persistencia de los días anteriores;
10. etiquetas de procedencia en bot y contexto de IA;
11. validadores defensivos y fallback sólo ante datos válidos;
12. VO2max Zepp observado por entrenamiento, sin anular VO2max Garmin;
13. clasificación `partial` y conteo de días del proveedor;
14. upsert por usuario, fecha y fuente sin duplicados.

Se considerará terminado cuando una sincronización completa mantenga las
actividades Garmin intactas, publique los tres días de wellness normalizado y
muestre las métricas efectivas con su procedencia, incluso si Zepp está ausente
o falla.
