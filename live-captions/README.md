# Subtítulos en vivo

Transcribe una conversación mientras ocurre, para seguir mejor a alguien que habla rápido o con un acento difícil. Entiende inglés de EE. UU., inglés con acento de India y español.

- **Subtítulos** frase por frase, con unos 2 o 3 segundos de demora y el idioma detectado.
- **Traducción opcional** de cada frase al español o al inglés.
- **"¿Qué me preguntó?"**: reformula en palabras simples lo último que se dijo, en español o en inglés.
- **Glosario** de términos técnicos para que la traducción y la aclaración los escriban bien.
- **Fuente de audio:** micrófono, o el audio de una pestaña o ventana (Chrome/Edge). Esta última sirve para llamadas en el navegador cuando usás auriculares.
- **Privacidad:** barra roja visible mientras captura, pausar y detener, y nada guardado en disco salvo que lo actives.

Usalo con el conocimiento de las personas que participan: el audio se envía a ElevenLabs y el texto a Claude.

## Instalación

```bash
cd live-captions
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env       # ELEVENLABS_API_KEY y ANTHROPIC_API_KEY
python app.py              # http://127.0.0.1:8001
```

Abrilo en `127.0.0.1` o `localhost`: el navegador solo da acceso al audio ahí o en HTTPS.

## Cómo funciona

El navegador detecta las pausas al hablar y envía cada frase por WebSocket. El servidor la transcribe con ElevenLabs Speech-to-Text. Con el idioma en automático, se detecta en cada frase. Si activaste la traducción, Claude traduce la frase sin frenar los subtítulos siguientes.

## Configuración (`.env`)

| Variable | Default |
|---|---|
| `ELEVENLABS_STT_MODEL` | `scribe_v1` |
| `CLAUDE_MODEL` | `claude-opus-5-5` |
| `CLAUDE_EFFORT` | `low` (más rápido para traducir) |

Las transcripciones guardadas van a `transcripts/`, que no se sube a git.
