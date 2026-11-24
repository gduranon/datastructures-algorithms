# Simulador de entrevista

Práctica de entrevista para AI Architect: la app muestra una pregunta, vos respondés hablando, la respuesta se transcribe con ElevenLabs Speech-to-Text y Claude la evalúa.

La transcripción detecta sola el idioma y entiende inglés con acento de EE. UU., inglés con acento de India y español. Si en respuestas muy cortas detecta mal el idioma, podés fijarlo en "Solo inglés" o "Solo español".

Cada respuesta recibe:
- Puntaje de 1 a 5 y un veredicto.
- Qué cubriste y qué faltó.
- Feedback sobre la comunicación oral.
- Una respuesta modelo.
- Una repregunta, que podés responder en el momento.

## Preguntas

- 96 del banco del quiz (`../quiz/quiz_questions.json`). La opción correcta y la explicación se usan como referencia para evaluar.
- 14 abiertas de arquitectura y liderazgo, en español e inglés (`questions_open.json`).

## Instalación (en tu máquina)

```bash
cd interview-sim
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env       # completá ELEVENLABS_API_KEY y ANTHROPIC_API_KEY
python app.py              # abre en http://127.0.0.1:8000
```

Abrí la app en `http://127.0.0.1:8000`, no en la IP de la red: el navegador solo da acceso al micrófono en `localhost` o HTTPS.

## Uso

1. Elegí idioma, tipo de pregunta y módulo, y presioná **Empezar**.
2. Con la opción automática activada, la grabación empieza al mostrarse la pregunta y corta tras el silencio configurado (1,8, 2,5 o 4 s). También podés cortar con **Terminé de responder**.
3. Revisá o corregí la transcripción; arriba se ve el idioma detectado. En modo automático se evalúa sola.
4. Tras el feedback podés **Responder repregunta**, **Reintentar esta pregunta** o pasar a la **Siguiente pregunta**.

El historial se guarda en `sessions/AAAA-MM-DD.jsonl`, que no se sube a git.

## Configuración opcional (`.env`)

| Variable | Default |
|---|---|
| `ELEVENLABS_STT_MODEL` | `scribe_v1` |
| `CLAUDE_MODEL` | `claude-opus-5-5` |

Las evaluaciones usan pensamiento adaptativo con esfuerzo `medium` y salida JSON validada. También tienen activado el fallback del lado del servidor por si el modelo rechaza una evaluación.
