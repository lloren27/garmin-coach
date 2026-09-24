# Diseño: importación de actividades Zepp como respaldo de Garmin

## Objetivo

Permitir que Garmin Coach analice una actividad registrada en Zepp cuando
Garmin no haya registrado esa misma sesión. El usuario podrá solicitarla desde
Telegram con `/sync zepp`; la actividad resultante participará en los
resúmenes, carga basada en duración/FC, feedback y contexto de Ollama igual que
una actividad Garmin en los campos que ambas fuentes comparten.

Garmin sigue siendo la referencia para actividades duplicadas y para sus
métricas propietarias. Zepp deja de ser exclusivamente una fuente wellness,
pero no pasa a sustituir datos Garmin ya disponibles.

## Validación previa (P0)

La actividad de hoy aparece en la app Zepp como «Correr al aire libre». La
misma pareja local `ZEPP_TOKEN`/`ZEPP_USER_ID` que ya alimenta wellness y
composición corporal devolvió el índice de entrenamientos al usar la identidad
web correcta: `appPlatform: web` y `appname: com.xiaomi.hm.health`. El índice
incluye el registro candidato de hoy y publica, entre otros, identificador de
actividad, procedencia, tipo de deporte, timestamps, distancia, duración,
ritmo, FC media/máxima, calorías, elevación y carga Zepp.

Una consulta anterior con la identidad iOS devolvió un índice vacío. Por tanto,
la integración de actividades no reutilizará ciegamente las cabeceras de otros
clientes: el adaptador de actividades será dueño de las cabeceras web. No se
requieren un token o usuario diferentes entre Zepp y Zepp Life para esta
cuenta; las actividades visibles pertenecen a la cuenta Zepp ya configurada.

## Alcance y límites

La sincronización local en el Mac consulta el índice no oficial de actividades
Zepp y filtra un intervalo reciente configurable. El valor predeterminado será
`ZEPP_ACTIVITY_SYNC_LOOKBACK_DAYS=3`, que cubre hoy y los dos días previos,
para protegerse frente a sincronización tardía del dispositivo o de la app.

`/sync zepp` solicita expresamente esa importación. `/sync` conserva su
significado de sincronización completa y también usa el mismo proveedor de
actividades Zepp; así una actividad ya subida a Zepp se recupera sin requerir
un segundo comando. El comando no puede obligar a la Helio Strap a sincronizar
por Bluetooth con el teléfono ni a Zepp móvil a publicar datos que aún no estén
en Zepp Cloud. Si la sesión todavía no existe en cloud, el resultado debe
indicarlo como ausencia de actividad, no crear una sesión inferida.

No se descargan archivos FIT/GPX, series por segundo, rutas ni datos sensibles
del dispositivo en esta primera entrega. Tampoco se envían actividades Zepp a
Wattwise: ese puente depende de archivos Garmin. La carga propietaria
`exercise_load` de Zepp se conserva sólo como metadato fuente y nunca se suma a
`activityTrainingLoad` de Garmin.

## Arquitectura

```text
Zepp Cloud activity history
            |
    ZeppActivityProvider
            |
  ActivityNormalizer (Zepp -> contrato común)
            |
 Garmin activities --+--> merge_activities() --> summarize() --> payload
            |
   Garmin wins on an exact duplicate
```

`ZeppActivityProvider` es el único módulo que conoce la URL, los encabezados
web y los nombres de campos del índice de Zepp. Expone una lectura de
actividades para una ventana de fechas y un estado redactado (`ok`, `partial`,
`disabled`, `auth_error`, `network_error`, `api_error`, `invalid_data`). No
registra el token, el `user_id` ni la respuesta sin normalizar.

El normalizador produce el mismo contrato compacto consumido por los resúmenes
existentes. Cada actividad tendrá un id estable con prefijo de proveedor,
`id: "zepp:<source>:<trackid>"`, y conservará `source: "zepp"` junto con
`source_activity_id`, sin alterar los identificadores Garmin. Los campos
normalizados comunes son:

```json
{
  "id": "zepp:...",
  "source": "zepp",
  "source_activity_id": "...",
  "date": "2026-09-24",
  "started_at": "2026-09-24T07:25:00+02:00",
  "name": "Correr al aire libre",
  "sport": "running",
  "type": "outdoor_running",
  "km": 8.02,
  "duration_s": 2518,
  "hours": 0.7,
  "pace": "5:12/km",
  "avg_speed_kmh": 11.5,
  "avg_hr": 0,
  "max_hr": 0,
  "calories": 0,
  "elevation_gain_m": 0,
  "provider_exercise_load": { "value": 0, "source": "zepp" }
}
```

Los ceros del ejemplo son sólo ilustrativos de campos opcionales: el
normalizador omite una métrica que el origen no proporcione o no pueda validar.
Los timestamps se convierten a ISO-8601 con la zona horaria del atleta; fechas,
distancias y duraciones inválidas descartan el registro.

## Fusión y deduplicación

El sincronizador primero normaliza Garmin y Zepp por separado y luego aplica
`merge_activities(garmin, zepp)`. Jamás concatena respuestas crudas de las dos
APIs. Un mismo proveedor se deduplica por su id estable.

Una actividad Zepp se considera duplicada de una Garmin sólo cuando se cumplen
todos estos criterios:

1. mismo deporte normalizado;
2. inicios con menos de diez minutos de diferencia;
3. solapamiento temporal de al menos el 70% de la sesión más corta;
4. si ambas contienen distancia positiva, diferencia relativa de distancia no
   superior al 10%.

Cuando existe duplicado, Garmin se conserva y Zepp se excluye de todos los
totales. Si falta cualquier dato necesario para demostrar la coincidencia, se
conservan ambas: es preferible revisar una sesión adicional a perder una
actividad real. El merge ordena por `started_at` y conserva el contrato actual
de `summary.activities`, por lo que `/hoy`, semana, fatiga y Ollama no precisan
un segundo formato.

## Análisis y procedencia

Una actividad únicamente Zepp entra en los kilómetros, duración, sesiones,
fatiga, carga de carrera, feedback y contexto de IA. Los formateadores muestran
`[Zepp]` donde describan la actividad o su carga para mantener trazabilidad.

Para una carrera Zepp con FC media y perfil válido, el módulo existente estima
TRIMP Banister usando el perfil del atleta; ese resultado se etiqueta
`trimp_estimado`, igual que para cualquier actividad sin carga Garmin directa.
Si no hay base suficiente para estimar TRIMP, la actividad sigue contando en
duración, distancia y frecuencia, pero no inventa carga. `exercise_load` Zepp
se muestra sólo como referencia separada y no participa en ACWR ni sustituye
un `activityTrainingLoad` Garmin.

Wattwise, potencia Garmin, FTP, Training Effect Garmin y archivos de actividad
permanecen sin datos para una sesión originada sólo en Zepp. El bot debe decir
«no disponible para esta actividad Zepp» en lugar de presentarlos como ceros.

## Comando y sincronización solicitada

El parser de Telegram acepta `/sync zepp` sin crear un comando paralelo. El
backend persiste la solicitud con `mode: "zepp_activities"`, muestra que se
solicitó una importación Zepp y conserva el solicitante y timestamp. El watcher
del Mac recibe ese modo, ejecuta el sync completo —manteniendo Garmin,
wellness y la nueva lectura Zepp— y completa la solicitud sólo tras el POST
correcto del payload.

Una petición normal `/sync` se guarda con `mode: "full"`. El watcher conserva
su comportamiento de datos caducados y no ejecuta repetidamente una petición
ya completada. Si Zepp falla pero Garmin funciona, el sync se publica con el
estado de Zepp y la solicitud se marca como completada; un fallo que impida
publicar el payload se marca como `failed` con un error redactado.

## Pruebas y criterios de aceptación

La implementación debe probar:

1. consulta Zepp con las cabeceras web correctas y sin exponer secretos;
2. normalización de carrera Zepp con timestamps, distancia, duración, ritmo,
   FC, calorías y procedencia;
3. registros inválidos, respuesta vacía y token caducado;
4. selección por ventana de fechas y deduplicación por id Zepp;
5. inclusión de una actividad Zepp sin Garmin en resúmenes de hoy, semana,
   fatiga y contexto de IA;
6. Garmin ganador para una sesión duplicada y dos sesiones independientes del
   mismo día preservadas;
7. no mezclar `exercise_load` Zepp con carga Garmin ni enviar Zepp a Wattwise;
8. `/sync zepp` guarda el modo correcto, el watcher lo respeta y la respuesta
   Telegram comunica la petición;
9. `/sync` normal sigue siendo compatible;
10. regresión completa de los tests del sync local y del bot.
