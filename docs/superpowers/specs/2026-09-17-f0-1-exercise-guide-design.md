# F0.1 — Exercise Guide

## Objetivo

Crear un catálogo técnico estático para los doce ejercicios de los circuitos de fuerza A y B. Cada ejercicio podrá recuperar su guía mediante su `exercise_id`, sin cambiar todavía la experiencia de Telegram ni el registro, resumen o cálculo de carga de las sesiones.

## Alcance

F0.1 añade en la capa de fuerza:

- un diccionario `STRENGTH_GUIDES`, separado de `CIRCUITS` y cuyas claves son los identificadores estables de sus ejercicios;
- una guía completa en español para cada uno de los doce ejercicios;
- una función `get_strength_guide(exercise_id)` que hace un lookup exacto y devuelve la guía correspondiente o `None` para un identificador desconocido;
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

La implementación hace un lookup exacto, sin normalización:

```python
def get_strength_guide(exercise_id: str) -> dict[str, Any] | None:
    return STRENGTH_GUIDES.get(exercise_id)
```

Para un ID conocido devuelve la entrada de `STRENGTH_GUIDES`. Para un ID desconocido devuelve `None`. Por tanto, `get_strength_guide("sentadilla")` encuentra la guía, mientras que `get_strength_guide("Sentadilla")` y `get_strength_guide("squat")` devuelven `None`. La resolución de nombres, alias y variantes normalizadas pertenece a F0.2.

## Organización del código

El catálogo y su función de acceso vivirán en un módulo nuevo e independiente:

```text
apps/bot/app/strength.py
apps/bot/app/strength_guides.py
apps/bot/tests/test_strength_sessions.py
apps/bot/tests/test_strength_guides.py
```

`strength_guides.py` contendrá únicamente `STRENGTH_GUIDES` y `get_strength_guide()`. `strength.py` seguirá siendo propietario de circuitos, parsing, sesiones, histórico y cálculos de carga. Las pruebas del nuevo catálogo se aislarán en `test_strength_guides.py`; la suite existente verificará que el comportamiento de fuerza no cambia.

## Integridad y pruebas

Las pruebas derivarán la lista de IDs directamente desde `CIRCUITS`, comprobarán primero que no existen duplicados y después exigirán igualdad exacta con las claves de `STRENGTH_GUIDES`:

```python
all_exercise_ids = [
    exercise["id"]
    for exercises in CIRCUITS.values()
    for exercise in exercises
]

assert len(all_exercise_ids) == len(set(all_exercise_ids))
assert set(STRENGTH_GUIDES) == set(all_exercise_ids)
```

Así se detectan IDs duplicados, ejercicios sin guía y guías huérfanas. El contrato resultante es: doce ejercicios, doce IDs únicos, doce guías y una guía por `exercise_id`. Además, las pruebas comprobarán:

1. Que existen exactamente doce ejercicios y sus IDs son únicos.
2. Que cada guía contiene exactamente `objective`, `cues`, `errors` y `media`.
3. Que `objective` es una cadena no vacía.
4. Que `cues` y `errors` son tuplas no vacías cuyos elementos son cadenas no vacías.
5. Que `media` es `None` en F0.1.
6. Que `get_strength_guide("sentadilla")` devuelve la guía de sentadilla.
7. Que `get_strength_guide("no_existe")`, `get_strength_guide("Sentadilla")` y `get_strength_guide("squat")` devuelven `None`.
8. Que la suite existente de fuerza sigue pasando sin cambios de comportamiento.

## Criterio de terminado

Los doce ejercicios declarados en `CIRCUITS` tienen IDs únicos y una guía técnica estática accesible mediante lookup exacto en `get_strength_guide()`. Las pruebas garantizan correspondencia exacta entre ambos catálogos, ausencia de IDs duplicados y que ningún comportamiento existente de fuerza cambia.
