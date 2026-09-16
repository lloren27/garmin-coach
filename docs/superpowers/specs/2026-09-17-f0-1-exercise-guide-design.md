# F0.1 — Exercise Guide

## Objetivo

Crear un catálogo técnico estático para los doce ejercicios de los circuitos de fuerza A y B. Cada ejercicio podrá recuperar su guía mediante su `exercise_id`, sin cambiar todavía la experiencia de Telegram ni el registro, resumen o cálculo de carga de las sesiones.

## Alcance

F0.1 añade en la capa de fuerza:

- un diccionario `STRENGTH_GUIDES`, separado de `CIRCUITS` y cuyas claves son los identificadores estables de sus ejercicios;
- una guía completa en español para cada uno de los doce ejercicios;
- una función `get_strength_guide(exercise_id)` que devuelve la guía correspondiente o `None` para un identificador desconocido;
- pruebas que garantizan la correspondencia exacta y la estructura de ambos catálogos.

Quedan expresamente fuera de este sprint:

- comandos `/fuerza tecnica`;
- cualquier integración o cambio en Telegram;
- imágenes, GIF o vídeo;
- prescripción y progresión;
- integración con Ollama;
- cambios en sesiones o en su persistencia;
- cambios en `summarize_strength_load()`, `strength_recovery_risk()` o `load_score`.

## Modelo de datos

`STRENGTH_GUIDES` se define como un diccionario indexado por `exercise_id`. Cada valor tiene exactamente estos campos:

```python
{
    "objective": "Fortalecer cuádriceps y glúteos mediante un patrón de sentadilla.",
    "cues": (
        "Mantén el apoyo estable del pie",
        "Rodillas siguiendo la dirección de los pies",
        "Mantén el tronco estable",
        "Controla el descenso",
    ),
    "errors": (
        "Rodillas colapsando hacia dentro",
        "Perder el control del tronco",
        "Descenso sin control",
    ),
    "media": None,
}
```

`cues` y `errors` son tuplas porque forman parte de un catálogo estático. No se introducirán todavía `TypedDict`, dataclasses, Pydantic, JSON externo ni validación en tiempo de ejecución. El campo `media` queda reservado con valor `None` hasta F0.3.

## Acceso

La interfaz pública será:

```python
get_strength_guide("sentadilla")
```

Para un ID conocido devuelve la entrada de `STRENGTH_GUIDES`. Para un ID desconocido devuelve `None`. La función acepta identificadores estables; la resolución de nombres y alias pertenece a F0.2.

## Integridad y pruebas

Las pruebas derivarán el conjunto de IDs directamente desde `CIRCUITS` y exigirán igualdad exacta con las claves de `STRENGTH_GUIDES`:

```python
exercise_ids = {
    exercise["id"]
    for exercises in CIRCUITS.values()
    for exercise in exercises
}

assert set(STRENGTH_GUIDES) == exercise_ids
```

Así se detectan tanto ejercicios sin guía como guías huérfanas. Además, las pruebas comprobarán:

1. Que cada guía contiene exactamente `objective`, `cues`, `errors` y `media`.
2. Que `objective` es una cadena no vacía.
3. Que `cues` y `errors` son tuplas no vacías cuyos elementos son cadenas no vacías.
4. Que `media` es `None` en F0.1.
5. Que `get_strength_guide("sentadilla")` devuelve la guía de sentadilla.
6. Que `get_strength_guide("no_existe") is None`.
7. Que la suite existente de fuerza sigue pasando sin cambios de comportamiento.

## Criterio de terminado

Los doce IDs declarados en `CIRCUITS` tienen una guía técnica estática accesible mediante `get_strength_guide()`, las pruebas garantizan correspondencia exacta entre ambos catálogos y ningún comportamiento existente de fuerza cambia.
