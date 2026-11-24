# Asistente de conversación en vivo

Transcribe una conversación mientras ocurre, para seguir mejor a alguien que habla rápido o con un acento difícil. Entiende inglés de EE. UU., inglés con acento de India y español.

- **Subtítulos** frase por frase, con unos 2 o 3 segundos de demora y el idioma detectado.
- **Traducción opcional** de cada frase al español o al inglés.
- **"¿Qué me preguntó?"**: reformula en palabras simples lo último que se dijo, en español o en inglés.
- **Preguntas detectadas**, directas o indirectas, aunque queden partidas en varias frases.
- **Respuestas sugeridas en streaming**: puntos clave, respuesta completa en lenguaje coloquial, siglas explicadas en letra chica y un esquema dibujado (flujo, mapa o tabla). Podés dar datos tuyos y del tema para personalizarlas.
- **TTS 11Labs / TTS macOS**: botón que muestra el motor en uso y permite transcribir en la Mac, sin red, si ElevenLabs no está disponible. Requiere macOS 26 o posterior y Xcode o sus herramientas de línea de comandos; se compila solo la primera vez.
- **Doble transcripción**: con 11Labs u OpenAI, macOS transcribe también cada frase. Si llega primero con confianza alta se usa enseguida; si el otro motor después entendió otra cosa, se agrega como segunda versión y, si cambia la pregunta, como otra pregunta con su respuesta. Si el otro motor falla, queda la de macOS.
- **Pregunta escrita**: escribí una pregunta y recibís la respuesta con el mismo formato. Tiene en cuenta toda la transcripción y las preguntas y respuestas anteriores de la conversación.
- **Entrevistas**: pegá la descripción del rol en Ajustes. Lo que pregunta el entrevistador y lo que responde el entrevistado se guarda por separado en `transcripts/interviews/<fecha>/`. Marcá "Soy yo" en tu voz para separarlos mejor.
- **Evaluar entrevista**: al terminar, puntaje de 0 a 100 según cinco criterios, fortalezas, mejoras y detalle por pregunta. Evalúa lo dicho, no las sugerencias. Es una opinión de la IA, orientativa.
- **Copiar y exportar**: copiá una pregunta con su respuesta o todas, y descargá la transcripción completa en `.txt`.
- **Preguntas guardadas**: preguntas, respuestas y esquemas se guardan en `transcripts/questions.json` y se recargan contraídos al iniciar. Un clic en el título abre o cierra cada uno.
- **Empezar de cero**: en Ajustes, un botón borra las transcripciones y preguntas guardadas en disco, y la conversación actual. "Borrar conversación" conserva las preguntas guardadas.
- **Historial contextual**: las últimas frases van textuales y las anteriores resumidas. Sobrevive a recargar la página, no a reiniciar el servidor.
- **Línea de tiempo** con los temas tratados; un clic lleva a ese momento.
- **Pregunta o respuesta**: cada frase se etiqueta y las respuestas enlazan a su pregunta.
- **Interlocutores**: distingue voces en tu computadora. Podés nombrarlas, unir dos poniéndoles el mismo nombre y marcar "Soy yo" para no recibir sugerencias a tus propias preguntas.
- **Glosario** de términos técnicos para que la traducción y la aclaración los escriban bien.
- **Fuente de audio:** micrófono, o el audio de una pestaña o ventana (Chrome/Edge). Esta última sirve para llamadas en el navegador cuando usás auriculares.
- **Privacidad:** barra roja visible mientras captura, pausar y detener, y la transcripción, las preguntas y las entrevistas se guardan siempre en `transcripts/`, solo en tu computadora, hasta que las borres.

Usalo con el conocimiento de las personas que participan: el audio se envía al proveedor de voz y el texto al proveedor de IA.

## Instalación

```bash
cd live-captions
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python speakers.py         # descarga el modelo de voces (29 MB)
cp .env.example .env       # ELEVENLABS_API_KEY y ANTHROPIC_API_KEY
python app.py              # http://127.0.0.1:8001
```

Abrilo en `127.0.0.1` o `localhost`: el navegador solo da acceso al audio ahí o en HTTPS.

## Cómo funciona

El navegador detecta las pausas al hablar y envía cada frase por WebSocket. El servidor la transcribe con ElevenLabs Speech-to-Text. Con el idioma en automático, se detecta en cada frase. Si activaste la traducción, Claude traduce la frase sin frenar los subtítulos siguientes.

## Configuración (`.env`)

| Variable | Default | Uso |
|---|---|---|
| `STT_PROVIDER` | `elevenlabs` | Voz: `elevenlabs`, `openai` o `macos` |
| `LLM_PROVIDER` | `anthropic` | IA: `anthropic` u `openai` |
| `ELEVENLABS_API_KEY`, `ELEVENLABS_STT_MODEL` | -, `scribe_v1` | ElevenLabs |
| `ANTHROPIC_API_KEY`, `CLAUDE_MODEL`, `CLAUDE_EFFORT` | -, `claude-opus-5-5`, `low` | Claude |
| `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_MODEL` | -, API de OpenAI, - | OpenAI o API compatible |
| `OPENAI_STT_MODEL`, `OPENAI_STT_BASE_URL`, `OPENAI_STT_API_KEY` | `whisper-1`, igual que el LLM | Voz con API compatible |
| `SPEAKER_THRESHOLD` | `0.55` | Subilo si mezcla personas; bajalo si divide a una en varias |
| `MACOS_CONFIDENCE` | `0.9` | Confianza mínima (0 a 1) para usar macOS sin esperar al otro motor |
| `CONTEXT_SEGMENTS` | `40` | Frases textuales antes de resumir |

Reiniciá la app después de cambiar `.env`. Con las sugerencias o la clasificación activas, cada frase (o grupo de frases) genera una llamada al LLM, y cada pregunta detectada genera otra para la respuesta completa y el esquema.

Inglés de EE. UU. y de India usan el mismo código de idioma al transcribir. La opción elegida orienta al LLM para corregir errores.

Las transcripciones guardadas van a `transcripts/`, que no se sube a git.
