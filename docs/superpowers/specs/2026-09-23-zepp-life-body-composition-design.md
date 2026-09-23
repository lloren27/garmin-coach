# Diseño: composición corporal desde Zepp Life

## Objetivo

Incorporar las mediciones de Mi Body Composition Scale 2 disponibles en Zepp
Life al contexto de Garmin Coach. El sistema conservará las pesadas atómicas,
una vista actual y tendencias de 7 y 28 días. Esta información contextualiza el
coaching, pero no modifica por sí sola las prescripciones de entrenamiento.

## Validación previa (P0)

La cuenta real respondió correctamente a una consulta de solo lectura de los
últimos 30 días. El endpoint devolvió cinco pesadas y los campos de resumen
incluyeron peso, BMI, porcentaje de grasa, agua, masa ósea, metabolismo,
porcentaje muscular, grasa visceral, edad muscular y puntuaciones corporales.
No devolvió masa muscular en kg. El cliente actual `zepp-export` no ofrece este
endpoint, de modo que esta integración no dependerá de él.

## Alcance y límites

La funcionalidad vive exclusivamente en el sincronizador local del Mac. Usa
las credenciales Zepp existentes desde el `.env` local y no las transmite a
Railway. La ventana predeterminada será de 35 días, configurable mediante
`ZEPP_BODY_COMPOSITION_LOOKBACK_DAYS`, para poder calcular tendencias de 28
días incluso si el atleta omite algunas pesadas.

No se incorporarán actividades de Zepp, identificadores de usuario, números de
serie de dispositivos, nombre de aplicaciones externas ni impedancia cifrada.
No se calculará masa muscular en kg ni edad metabólica cuando el proveedor no
las publique. Las métricas BIA se identificarán como estimaciones y no se
usarán para concluir cambios relevantes a partir de una sola pesada.

## Arquitectura

El contrato de dominio no quedará acoplado a un endpoint concreto:

```text
Mi Body Composition Scale 2
        |
    Zepp Life
        |
ZeppLifeScaleProvider  --implements-->  BodyCompositionProvider
        |
BodyCompositionNormalizer
        |
wellness.body_composition
```

`BodyCompositionProvider` define una operación de lectura de registros para un
intervalo y devuelve un resultado con estado redactado. `ZeppLifeScaleProvider`
será la primera implementación y consultará el endpoint Zepp Life validado en
P0 mediante HTTP, con las mismas credenciales locales. El normalizador acepta
la respuesta externa y produce modelos JSON seguros, independientes del
proveedor. Ninguna otra capa conoce URLs, cabeceras o campos de transporte.

Un error de esta fuente no debe convertir el sync Garmin en fallido: se
publicará un estado `disabled`, `auth_error`, `network_error`, `api_error`,
`invalid_data` u `ok`, sin incluir secretos ni cuerpos de respuesta. Una
respuesta correcta sin pesadas se representa como `ok` con historial vacío.

## Contrato de datos

La composición corporal no es una métrica diaria intercambiable entre Garmin y
Zepp. Se mantiene separada de `wellness.effective`, que sigue representando
solamente la resolución de wellness diario:

```json
{
  "wellness": {
    "schema_version": 2,
    "body_composition": {
      "source": "zepp_life",
      "provider_status": { "status": "ok", "records_received": 5 },
      "lookback_days": 35,
      "latest": {
        "observed_at": "2026-09-23T07:31:00+02:00",
        "weight_kg": 87.1,
        "bmi": 24.4,
        "body_fat_pct": 18.2,
        "muscle_pct": 54.1,
        "body_water_pct": 58.7,
        "bone_mass_kg": 3.4,
        "visceral_fat_index": 8,
        "basal_metabolism_kcal": 1876,
        "muscle_age": 34,
        "source": "zepp_life"
      },
      "history": [],
      "trends": { "7d": {}, "28d": {} }
    }
  }
}
```

`muscle_age` sólo estará presente si el origen lo publica. No se derivará una
edad metabólica a partir de ese valor. `muscle_mass_kg` permanece ausente hasta
que una fuente fiable lo aporte. Cada registro conserva sólo
campos numéricos válidos, `observed_at` ISO-8601 con offset y
`source: "zepp_life"`.

El mapeo inicial es: `weight` a `weight_kg`, `fatRate` a `body_fat_pct`,
`muscleRate` a `muscle_pct`, `bodyWaterRate` a `body_water_pct`, `boneMass` a
`bone_mass_kg`, `metabolism` a `basal_metabolism_kcal`, `visceralFat` a
`visceral_fat_index`, `bmi` a `bmi` y `muscleAge` a `muscle_age`. Los
campos de puntuación sólo se añadirán cuando su semántica y unidad estén claras
en la respuesta; no forman parte del contrato inicial de coaching.

## Múltiples pesadas y tendencias

`history` conserva todas las lecturas válidas, ordenadas por `observed_at`.
`latest` es exactamente la última lectura válida cronológicamente. Los
registros no se mezclan ni se completan campo a campo entre dispositivos.

Para tendencias se construye una observación representativa por fecha local:
la mediana independiente de cada métrica entre las pesadas de ese día. De este
modo, repeticiones accidentales no dominan el cálculo. Para cada ventana móvil
de 7 o 28 días se usan únicamente los días con representación válida.

Una tendencia incluye `status`, `samples`, `days_covered`, `from_observed_at`,
`to_observed_at` y, cuando hay suficiente cobertura, `weight_avg_kg`,
`weight_change_kg`, `body_fat_avg_pct` y `body_fat_change_pct_points`. El
cambio es la diferencia entre la mediana del bloque inicial y la del bloque
final de hasta tres días representativos disponibles; reduce el ruido frente a
comparar una única lectura antigua con una única lectura reciente. Los mínimos
son tres días representativos para `7d` y cinco para `28d`. Por debajo de esos
mínimos la tendencia será `{ "status": "insufficient_data", "samples": n }`
y no publicará cambios.

El historial y las tendencias se recalculan completamente desde la ventana
Zepp en cada sync. El payload completo se guarda a través del flujo de sync ya
existente; no se añade una tabla específica en esta primera entrega. Un fallo
actual de Zepp se comunica mediante el estado del proveedor, sin presentar un
valor anterior como lectura recién obtenida.

## Consumidores

`/salud` mostrará, si existen, la fecha y procedencia del último peso, las
estimaciones BIA disponibles y las tendencias de 7/28 días. No se añadirá a
`/hoy`, que se mantiene centrado en el día y sus actividades. El contexto
compacto de Ollama incluirá `latest` y `trends`, pero no el historial completo.
La redacción indicará explícitamente que grasa corporal y composición son
estimaciones BIA y evitará inferencias fuertes basadas en variaciones diarias.

Las funciones de riesgo, recuperación y selección de sesiones no consumirán
esta nueva sección en esta entrega. Una futura regla de coaching que use
tendencias de peso requerirá una especificación y validación propias.

## Pruebas y criterios de aceptación

La implementación debe cubrir:

1. normalización de cada campo permitido y exclusión de los sensibles;
2. timestamps en segundos y milisegundos convertidos a la zona local;
3. historial conservando varias pesadas del mismo día y `latest` cronológico;
4. mediana diaria por métrica;
5. tendencias de 7/28 días con cambios robustos y mínimos de muestras;
6. `insufficient_data` sin cifras engañosas;
7. proveedor deshabilitado, token erróneo, red y API sin filtrar credenciales;
8. respuesta válida sin registros;
9. integración de payload sin modificar `wellness.effective` ni actividades
   Garmin;
10. salida de `/salud` y contexto de Ollama con procedencia y sin historial
    completo;
11. regresión completa de los tests locales de sync y del bot.
