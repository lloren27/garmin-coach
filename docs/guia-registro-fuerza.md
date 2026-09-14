# Guía de registro de fuerza

Esta guía explica cómo registrar una sesión de fuerza en el bot, qué formatos de entrada reconoce y cómo ampliar el sistema si se añaden ejercicios o datos nuevos.

## Flujo de una sesión

1. Inicia uno de los dos circuitos disponibles:

   ```text
   /fuerza A
   ```

   ```text
   /fuerza B
   ```

2. Registra cada ejercicio al terminar sus series.

3. Consulta lo registrado, si lo necesitas:

   ```text
   /fuerza actual
   ```

4. Cierra la sesión para guardar el resumen y que el entrenador use su carga al dar recomendaciones:

   ```text
   /fuerza fin
   ```

Puedes consultar las últimas sesiones cerradas con `/fuerza historial` y ver esta ayuda breve con `/fuerza ayuda`.

## Sintaxis de un registro

La forma recomendada es:

```text
/fuerza add <ejercicio> <peso> <series y repeticiones> <esfuerzo>
```

Por ejemplo:

```text
/fuerza add sentadilla 60kg 2x8 rir2
```

Este registro significa: sentadilla con 60 kg, dos series de ocho repeticiones y dos repeticiones en reserva (RIR 2).

Cada entrada necesita, al menos, un dato medible: peso, repeticiones, RIR o RPE. El orden recomendado evita ambigüedades y hace que el resumen sea más fácil de leer.

## Peso

Indica el peso seguido de `kg`, `kilo` o `kilos`. Se admiten decimales con coma o punto.

```text
/fuerza add remo 42.5kg 2x10 rir2
/fuerza add remo 42,5 kilos 2x10 rir2
```

El volumen se calcula como peso por el total de repeticiones. Si el ejercicio es con peso corporal o no se registra carga, la sesión se guarda igualmente, pero no se sumará volumen en kg.

```text
/fuerza add flexiones 2x10 rir2
```

## Series y repeticiones

Hay tres formatos válidos.

### Series iguales: `series x repeticiones`

```text
/fuerza add sentadilla 60kg 2x8 rir2
```

Representa dos series de ocho repeticiones. El sistema admite hasta diez series con este formato.

### Repeticiones de cada serie: separadas por `/`

```text
/fuerza add sentadilla 60kg 8/8/7 rir2
```

Representa tres series: 8, 8 y 7 repeticiones.

### Una sola serie

```text
/fuerza add sentadilla 60kg 8 rir2
```

Representa una serie de ocho repeticiones. Para que sea inequívoco también puedes escribir `8 reps` o `8 repeticiones`.

En ejercicios unilaterales, como la zancada, registra las repeticiones **por lado**. Por ejemplo, `2x10` significa dos series de diez por pierna; no debe usarse `10/10` para distinguir derecha e izquierda, porque el bot lo interpretaría como dos series.

## Esfuerzo: RIR y RPE

El bot acepta una de estas dos medidas:

- `rir2`: quedarían aproximadamente dos repeticiones antes del fallo.
- `rpe8`: esfuerzo percibido de ocho sobre diez.

Ejemplos:

```text
/fuerza add peso muerto rumano 70kg 2x8 rir2
/fuerza add remo 45kg 2x10 rpe8
```

Si se envían ambos, el resumen mostrará RIR. Para la progresión de esta rutina, el objetivo habitual es `rir2` o `rir3`, evitando el fallo.

## Circuito A

El circuito A incluye sentadilla, peso muerto rumano, remo, press o flexiones, gemelo y Pallof press.

```text
/fuerza A
/fuerza add sentadilla 60kg 2x8 rir2
/fuerza add peso muerto rumano 70kg 2x8 rir2
/fuerza add remo 45kg 2x10 rir2
/fuerza add press banca 40kg 2x8 rir2
/fuerza add gemelos 30kg 2x15 rir2
/fuerza add pallof press 15kg 2x10 rir2
/fuerza fin
```

Alias reconocidos:

| Ejercicio | Alias admitidos |
| --- | --- |
| Sentadilla | `sentadilla`, `squat` |
| Peso muerto rumano | `peso muerto rumano`, `rumano`, `rdl` |
| Remo | `remo` |
| Press o flexiones | `press banca`, `press`, `flexiones`, `flexion` |
| Gemelo | `gemelo`, `gemelos`, `calf raise` |
| Pallof press | `pallof`, `pallof press` |

## Circuito B

El circuito B incluye zancada o split squat, hip thrust, jalón, press vertical, sóleo y plancha lateral.

```text
/fuerza B
/fuerza add zancada 30kg 2x10 rir2
/fuerza add hip thrust 80kg 2x8 rir2
/fuerza add jalon al pecho 45kg 2x10 rir2
/fuerza add press militar 25kg 2x8 rir2
/fuerza add soleo 35kg 2x15 rir2
/fuerza add plancha lateral 2x10 rir2
/fuerza fin
```

Alias reconocidos:

| Ejercicio | Alias admitidos |
| --- | --- |
| Zancada o split squat | `zancada`, `zancadas`, `split squat`, `bulgara`, `bulgaras` |
| Hip thrust | `hip thrust`, `puente gluteo`, `puente gluteos` |
| Jalón | `jalon`, `jalon al pecho`, `dominadas`, `dominada` |
| Press vertical | `press vertical`, `press militar`, `hombro`, `hombros` |
| Sóleo | `soleo`, `soleos` |
| Plancha lateral | `plancha lateral`, `side plank` |

Las tildes y mayúsculas no afectan al reconocimiento: `jalón`, `JALON` y `jalon` se interpretan de la misma forma.

## Ejercicios personalizados

Puedes registrar un ejercicio que no pertenezca a los circuitos:

```text
/fuerza add curl biceps 12kg 2x12 rir2
```

Se guardará como ejercicio personalizado y contará en el total de series, repeticiones y volumen. No se asignará a un grupo muscular específico, por lo que su impacto en la carga de pierna o cadena posterior no se calculará con el mismo detalle que para los ejercicios predefinidos.

## Casos habituales

| Caso | Entrada recomendada |
| --- | --- |
| Peso corporal | `/fuerza add flexiones 2x10 rir2` |
| Dos series con diferentes repeticiones | `/fuerza add remo 45kg 10/8 rir2` |
| Una serie | `/fuerza add sentadilla 60kg 8 rir2` |
| Carga decimal | `/fuerza add remo 42,5kg 2x10 rpe8` |
| Ejercicio unilateral | `/fuerza add zancada 30kg 2x10 rir2` (10 por pierna) |
| Core sin peso | `/fuerza add plancha lateral 2x10 rir2` |
| Ejercicio no incluido | `/fuerza add curl biceps 12kg 2x12 rir2` |

Evita anotar dos ejercicios en el mismo mensaje. Envía una entrada por ejercicio para que cada uno quede clasificado y resumido correctamente.

## Qué calcula el bot

Al cerrar la sesión, el bot resume:

- número de ejercicios, series y repeticiones;
- volumen total en kg cuando hay carga registrada;
- series por grupo muscular;
- una puntuación de carga que considera el grupo muscular, las series, el peso/repeticiones y RIR o RPE.

La fuerza de pierna y de cadena posterior tiene mayor peso en la recomendación de recuperación. El entrenador la usa junto con la carga de running y ciclismo para proteger sesiones de calidad y la tirada larga.

## Cómo ampliar el sistema

La definición de circuitos y el lector de entradas están en `apps/bot/app/strength.py`.

### Añadir un ejercicio a un circuito

Añade una entrada al diccionario `CIRCUITS` con:

- `id`: identificador estable, sin espacios;
- `name`: nombre que se mostrará al usuario;
- `aliases`: formas admitidas al escribir el ejercicio;
- `group`: grupo muscular usado para calcular carga.

Ejemplo para incluir "curl femoral" en un circuito:

```python
{
    "id": "curl_femoral",
    "name": "curl femoral",
    "aliases": ("curl femoral", "leg curl"),
    "group": "isquios/gluteo",
},
```

Los grupos actuales son `cuadriceps/gluteo`, `isquios/gluteo`, `gluteo`, `gemelo/soleo`, `core`, `espalda`, `empuje` y `personalizado`. Si se crea un grupo nuevo, conviene añadir también su peso en `GROUP_LOAD_WEIGHT` y decidir si pertenece a `LOWER_BODY_GROUPS` o `POSTERIOR_GROUPS`.

### Añadir nuevos alias

Incluye las nuevas formas dentro de `aliases`. Los alias largos y específicos son preferibles cuando puedan coincidir con otros ejercicios. Por ejemplo, `press inclinado` debe añadirse antes de usar un alias genérico como `press` para evitar clasificaciones inesperadas.

### Añadir un formato de entrada

Los formatos se procesan en estas funciones:

- `_extract_weight_kg`: peso;
- `_extract_reps`: series y repeticiones;
- `_extract_metric`: RIR o RPE;
- `_match_exercise`: reconocimiento de ejercicio y alias.

Para incorporar, por ejemplo, duración de planchas, tempo o una carga por mancuerna, habría que ampliar el esquema que devuelve `parse_strength_entry`, guardar el nuevo campo en cada entrada y decidir cómo debe influir en el resumen y en la puntuación de carga.

### Pruebas necesarias al ampliar

Cada nuevo formato o ejercicio debe cubrirse en `apps/bot/tests/test_strength_sessions.py`. Como mínimo, verifica que se reconoce el ejercicio, que se extraen sus métricas, que el volumen es correcto cuando proceda y que el resumen de sesión refleja las series esperadas.
