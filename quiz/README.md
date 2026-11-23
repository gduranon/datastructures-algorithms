# AI Architect Prep · Quiz web

Quiz de opción múltiple para preparar la entrevista de AI Architect (agentes, Azure AI, RAG, ITSM, RCA, KPIs, seguridad, liderazgo).

**Uso:** abrir `index.html` en el navegador. No necesita servidor ni instalación.

- **Práctica:** por módulo, dificultad y cantidad; feedback inmediato o al final.
- **Examen simulado:** 30 o 60 preguntas equilibradas entre los 12 módulos, temporizador 30/60/90 min, umbral de aprobación configurable.
- **Repaso:** repetición espaciada (1/3/7/14/30 días), errores y favoritos.
- **Resultados:** desglose por módulo, dificultad y tipo, con la explicación de cada respuesta.
- **Simulador ROI** y **modo entrevista** (pitch, preguntas al empleador, plan 30-60-90).
- Progreso guardado en `localStorage`, con export/import JSON.
- Atajos: `1`–`4` / `A`–`D` para elegir, `Enter` para confirmar o pasar a la siguiente, `←` `→` para navegar en el examen.

## Estructura

- `quiz_questions.json`: banco de 96 preguntas (fuente de verdad).
- `src/app.html`: código de la app (HTML/CSS/JS sin dependencias).
- `build.py`: embebe el banco en la app y genera `index.html`. Ejecutá `python3 build.py` después de editar preguntas o código.
