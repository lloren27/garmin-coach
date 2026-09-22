# F0.1 Exercise Guide Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one static technical guide for each of the twelve strength exercises, accessible by exact `exercise_id`, without changing any existing strength behavior.

**Architecture:** Create a focused `app.strength_guides` module that owns the static content catalog and its exact lookup function. Keep `CIRCUITS` in `app.strength`; a separate test module imports both catalogs and enforces their one-to-one relationship in both directions.

**Tech Stack:** Python 3, standard-library type annotations, `unittest`.

**Spec:** `docs/superpowers/specs/2026-09-17-f0-1-exercise-guide-design.md`

## Global Constraints

- `cues` and `errors` must be non-empty tuples of non-empty strings.
- Every guide must contain exactly `objective`, `cues`, `errors`, and `media`.
- `media` must remain `None` throughout F0.1.
- `get_strength_guide()` must perform an exact dictionary lookup without normalization or alias resolution.
- Do not introduce `TypedDict`, dataclasses, Pydantic, JSON, or runtime validation.
- Do not change Telegram commands, sessions, persistence, prescription, progression, Ollama, media delivery, `summarize_strength_load()`, `strength_recovery_risk()`, or `load_score`.

## Review Focus

- A duplicate `exercise_id` inside or across circuits must fail the uniqueness test.
- A circuit exercise without a guide must fail the catalog equality test.
- A guide without a circuit exercise must fail the catalog equality test.
- A missing field, extra field, wrong container type, empty text, or non-`None` media value must fail schema validation.
- A case variant, display name, alias, or unknown value must return `None` rather than being normalized.

---

### Task 1: Static exercise-guide catalog and exact lookup

**Files:**
- Create: `apps/bot/app/strength_guides.py`
- Create: `apps/bot/tests/test_strength_guides.py`
- Verify unchanged: `apps/bot/app/strength.py`

**Interfaces:**
- Consumes: `app.strength.CIRCUITS: dict[str, list[dict[str, Any]]]` for test-time integrity checks only.
- Produces: `app.strength_guides.STRENGTH_GUIDES: dict[str, dict[str, Any]]`.
- Produces: `app.strength_guides.get_strength_guide(exercise_id: str) -> dict[str, Any] | None`.

- [ ] **Step 1: Write the failing catalog and lookup tests**

Create `apps/bot/tests/test_strength_guides.py`:

```python
from __future__ import annotations

import unittest

from app.strength import CIRCUITS
from app.strength_guides import STRENGTH_GUIDES, get_strength_guide


class StrengthGuideTests(unittest.TestCase):
    def test_circuit_exercise_ids_are_unique_and_match_guides_exactly(self) -> None:
        all_exercise_ids = [
            exercise["id"]
            for exercises in CIRCUITS.values()
            for exercise in exercises
        ]

        self.assertEqual(len(all_exercise_ids), 12)
        self.assertEqual(len(all_exercise_ids), len(set(all_exercise_ids)))
        self.assertSetEqual(set(STRENGTH_GUIDES), set(all_exercise_ids))

    def test_every_guide_has_valid_static_schema(self) -> None:
        expected_fields = {"objective", "cues", "errors", "media"}

        for exercise_id, guide in STRENGTH_GUIDES.items():
            with self.subTest(exercise_id=exercise_id):
                self.assertSetEqual(set(guide), expected_fields)
                self.assertIsInstance(guide["objective"], str)
                self.assertTrue(guide["objective"].strip())
                for field in ("cues", "errors"):
                    self.assertIsInstance(guide[field], tuple)
                    self.assertTrue(guide[field])
                    self.assertTrue(
                        all(isinstance(item, str) and item.strip() for item in guide[field])
                    )
                self.assertIsNone(guide["media"])

    def test_get_strength_guide_returns_exact_id_match(self) -> None:
        self.assertIs(
            get_strength_guide("sentadilla"),
            STRENGTH_GUIDES["sentadilla"],
        )

    def test_get_strength_guide_does_not_normalize_or_resolve_aliases(self) -> None:
        for exercise_id in ("no_existe", "Sentadilla", "squat", "sentadilla "):
            with self.subTest(exercise_id=exercise_id):
                self.assertIsNone(get_strength_guide(exercise_id))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the new test module and verify the expected failure**

Run:

```bash
PYTHONPATH=apps/bot python3 -m unittest apps.bot.tests.test_strength_guides -v
```

Expected: FAIL during import with `ModuleNotFoundError: No module named 'app.strength_guides'`.

- [ ] **Step 3: Implement the complete static catalog and exact lookup**

Create `apps/bot/app/strength_guides.py`:

```python
from __future__ import annotations

from typing import Any


STRENGTH_GUIDES: dict[str, dict[str, Any]] = {
    "sentadilla": {
        "objective": "Fortalecer cuádriceps y glúteos mediante un patrón de sentadilla.",
        "cues": (
            "Mantén el apoyo estable de todo el pie",
            "Lleva las rodillas en la dirección de los pies",
            "Mantén el tronco estable durante el recorrido",
            "Controla el descenso y sube empujando el suelo",
        ),
        "errors": (
            "Dejar que las rodillas colapsen hacia dentro",
            "Perder el control del tronco o de la zona lumbar",
            "Descender sin control o despegar los talones",
        ),
        "media": None,
    },
    "peso_muerto_rumano": {
        "objective": "Fortalecer isquios y glúteos mediante un patrón de bisagra de cadera.",
        "cues": (
            "Mantén una ligera flexión de rodillas",
            "Lleva la cadera hacia atrás con la espalda estable",
            "Mantén la carga cerca de las piernas",
            "Termina extendiendo la cadera sin inclinarte hacia atrás",
        ),
        "errors": (
            "Convertir el movimiento en una sentadilla",
            "Redondear la espalda durante el descenso",
            "Alejar la carga del cuerpo",
        ),
        "media": None,
    },
    "remo": {
        "objective": "Fortalecer la espalda y mejorar el control de las escápulas.",
        "cues": (
            "Mantén el tronco estable",
            "Inicia el movimiento llevando el codo hacia atrás",
            "Acerca la carga al cuerpo sin elevar el hombro",
            "Controla el regreso hasta extender el brazo",
        ),
        "errors": (
            "Girar o balancear el tronco para mover la carga",
            "Elevar el hombro hacia la oreja",
            "Acortar el recorrido o soltar el descenso",
        ),
        "media": None,
    },
    "press_flexiones": {
        "objective": "Fortalecer pecho, hombros y tríceps mediante un patrón de empuje horizontal.",
        "cues": (
            "Mantén muñecas y antebrazos alineados",
            "Coloca los codos en una posición cómoda, sin abrirlos en exceso",
            "Mantén el tronco estable durante todo el movimiento",
            "Controla el descenso y empuja de forma uniforme",
        ),
        "errors": (
            "Abrir los codos excesivamente",
            "Perder la posición del tronco o arquear la zona lumbar",
            "Rebotar o recortar el recorrido sin control",
        ),
        "media": None,
    },
    "gemelo": {
        "objective": "Fortalecer el gastrocnemio y mejorar la capacidad de impulsión del tobillo.",
        "cues": (
            "Mantén la rodilla extendida sin bloquearla con tensión",
            "Eleva el talón sobre el primer y segundo dedo del pie",
            "Alcanza una posición alta estable",
            "Desciende lentamente hasta recuperar el recorrido",
        ),
        "errors": (
            "Dejar que el tobillo se desplace hacia fuera",
            "Usar rebotes para completar las repeticiones",
            "Recortar el recorrido en la parte alta o baja",
        ),
        "media": None,
    },
    "pallof_press": {
        "objective": "Mejorar la estabilidad del tronco frente a fuerzas de rotación.",
        "cues": (
            "Coloca pelvis y caja torácica en una posición estable",
            "Mantén los pies firmes y las rodillas relajadas",
            "Extiende los brazos sin girar el tronco",
            "Respira mientras resistes la tracción lateral",
        ),
        "errors": (
            "Girar el tronco hacia el punto de anclaje",
            "Compensar arqueando la zona lumbar",
            "Usar una resistencia que impida mantener la posición",
        ),
        "media": None,
    },
    "zancada_split_squat": {
        "objective": "Fortalecer cuádriceps y glúteos con apoyo unilateral.",
        "cues": (
            "Mantén ambos pies estables durante la repetición",
            "Lleva la rodilla delantera en la dirección del pie",
            "Desciende de forma vertical con el tronco controlado",
            "Empuja el suelo con la pierna delantera para subir",
        ),
        "errors": (
            "Dejar que la rodilla delantera colapse hacia dentro",
            "Perder el equilibrio por una base demasiado estrecha",
            "Impulsarse principalmente con la pierna trasera",
        ),
        "media": None,
    },
    "hip_thrust": {
        "objective": "Fortalecer los glúteos mediante la extensión de cadera.",
        "cues": (
            "Apoya los pies de forma estable",
            "Mantén la barbilla ligeramente recogida",
            "Eleva la cadera contrayendo los glúteos",
            "Termina con pelvis y tronco alineados",
        ),
        "errors": (
            "Terminar el movimiento arqueando la zona lumbar",
            "Colocar los pies demasiado cerca o lejos de la cadera",
            "Rebotar en la parte baja o perder el control del descenso",
        ),
        "media": None,
    },
    "jalon": {
        "objective": "Fortalecer dorsales y brazos mediante un patrón de tracción vertical.",
        "cues": (
            "Mantén el pecho estable y los hombros alejados de las orejas",
            "Lleva los codos hacia abajo",
            "Acerca la barra al pecho sin forzar el cuello",
            "Controla la subida hasta extender los brazos",
        ),
        "errors": (
            "Tirar de la barra por detrás de la cabeza",
            "Balancear el tronco para mover más peso",
            "Encoger los hombros o soltar la fase de subida",
        ),
        "media": None,
    },
    "press_vertical": {
        "objective": "Fortalecer hombros y tríceps mediante un patrón de empuje vertical.",
        "cues": (
            "Mantén los pies firmes y el tronco estable",
            "Inicia con antebrazos aproximadamente verticales",
            "Empuja la carga sobre la cabeza sin perder la alineación",
            "Desciende de forma controlada hasta la posición inicial",
        ),
        "errors": (
            "Arquear en exceso la zona lumbar",
            "Adelantar la cabeza o perder la trayectoria de la carga",
            "Usar impulso de piernas cuando no está previsto",
        ),
        "media": None,
    },
    "soleo": {
        "objective": "Fortalecer el sóleo con la rodilla flexionada.",
        "cues": (
            "Mantén la rodilla flexionada durante toda la serie",
            "Apoya el antepié de forma estable",
            "Eleva el talón sin desviar el tobillo",
            "Controla el descenso hasta recuperar el recorrido",
        ),
        "errors": (
            "Extender la rodilla al subir",
            "Dejar que el tobillo caiga hacia dentro o fuera",
            "Rebotar o realizar repeticiones con recorrido incompleto",
        ),
        "media": None,
    },
    "plancha_lateral": {
        "objective": "Mejorar la estabilidad lateral del tronco y la pelvis.",
        "cues": (
            "Alinea hombro, cadera y tobillo",
            "Empuja el suelo con el antebrazo",
            "Mantén la pelvis elevada y estable",
            "Respira sin perder la posición",
        ),
        "errors": (
            "Dejar caer o girar la pelvis",
            "Hundirse sobre el hombro de apoyo",
            "Adelantar la cabeza o perder la alineación corporal",
        ),
        "media": None,
    },
}


def get_strength_guide(exercise_id: str) -> dict[str, Any] | None:
    return STRENGTH_GUIDES.get(exercise_id)
```

- [ ] **Step 4: Run the focused tests and verify they pass**

Run:

```bash
PYTHONPATH=apps/bot python3 -m unittest apps.bot.tests.test_strength_guides -v
```

Expected: four tests PASS.

- [ ] **Step 5: Run the complete bot test suite to detect regressions**

Run:

```bash
PYTHONPATH=apps/bot python3 -m unittest discover -s apps/bot/tests -v
```

Expected: all tests PASS, including the existing strength-session and load tests.

- [ ] **Step 6: Verify scope and repository diff**

Run:

```bash
git diff --check
git status --short
git diff -- apps/bot/app/strength.py
```

Expected: no whitespace errors; only `apps/bot/app/strength_guides.py` and `apps/bot/tests/test_strength_guides.py` are new; `apps/bot/app/strength.py` has no diff.

- [ ] **Step 7: Commit the completed sprint**

```bash
git add apps/bot/app/strength_guides.py apps/bot/tests/test_strength_guides.py
git commit -m "feat: add strength exercise guides"
```
