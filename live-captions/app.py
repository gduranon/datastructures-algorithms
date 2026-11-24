"""Subtítulos en vivo (inglés US, inglés de India, español) con traducción opcional.

El navegador captura audio (micrófono o audio de una pestaña), lo corta en frases por silencio
y envía cada frase por WebSocket. El servidor la transcribe con ElevenLabs Speech-to-Text,
la traduce opcionalmente con Claude y puede reformular lo último que se dijo en palabras simples.

Ejecutar:  python app.py  ->  http://127.0.0.1:8001
"""
from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime
from pathlib import Path

import anthropic
import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

HERE = Path(__file__).parent
load_dotenv(HERE / ".env")

ELEVEN_KEY = os.getenv("ELEVENLABS_API_KEY", "")
ELEVEN_STT_MODEL = os.getenv("ELEVENLABS_STT_MODEL", "scribe_v1")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-opus-5-5")
CLAUDE_EFFORT = os.getenv("CLAUDE_EFFORT", "low")  # baja latencia para traducción
TRANSCRIPTS = HERE / "transcripts"
STT_LANGS = {"auto": None, "eng": "eng", "spa": "spa"}
LANG_NAMES = {"eng": "inglés", "en": "inglés", "spa": "español", "es": "español"}

claude = anthropic.AsyncAnthropic()  # ANTHROPIC_API_KEY o perfil de `ant auth login`
app = FastAPI(title="Subtítulos en vivo")


@app.get("/")
def index():
    return FileResponse(HERE / "static" / "index.html")


@app.get("/api/config")
def config():
    return {"elevenlabs": bool(ELEVEN_KEY), "claude_model": CLAUDE_MODEL}


# ------------------------------------------------------------------ servicios
async def transcribe(http: httpx.AsyncClient, audio: bytes, lang: str) -> dict:
    form = {"model_id": ELEVEN_STT_MODEL, "tag_audio_events": "false"}
    if STT_LANGS.get(lang):
        form["language_code"] = STT_LANGS[lang]
    r = await http.post(
        "https://api.elevenlabs.io/v1/speech-to-text",
        headers={"xi-api-key": ELEVEN_KEY},
        data=form,
        files={"file": ("segment.webm", audio, "audio/webm")},
    )
    if r.status_code != 200:
        raise RuntimeError(f"ElevenLabs {r.status_code}: {r.text[:200]}")
    j = r.json()
    code = j.get("language_code")
    return {"text": (j.get("text") or "").strip(), "language": LANG_NAMES.get(code, code)}


async def ask_claude(system: str, user: str) -> str:
    resp = await claude.beta.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=4000,
        system=system,
        thinking={"type": "adaptive"},
        output_config={"effort": CLAUDE_EFFORT},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        messages=[{"role": "user", "content": user}],
    )
    if resp.stop_reason == "refusal":
        raise RuntimeError("El modelo no procesó este texto.")
    return next((b.text for b in resp.content if b.type == "text"), "").strip()


def glossary_note(glossary: str) -> str:
    return f"\nGlosario de términos técnicos que pueden aparecer mal transcritos: {glossary}" if glossary else ""


TRANSLATE_SYS = (
    "Traducís subtítulos de una conversación profesional en vivo. Devolvé solo la traducción, sin comillas ni notas. "
    "La transcripción automática puede tener errores (acentos de EE. UU., India o hispanohablantes): "
    "si una palabra mal transcrita es claramente un término técnico, usá el término correcto."
)
EXPLAIN_SYS = (
    "Ayudás a una persona a entender lo que acaba de decir su interlocutor en una conversación en vivo, "
    "porque el acento o la velocidad le dificultan seguirlo. Reformulá en palabras simples qué dijo o qué preguntó "
    "la otra persona en los últimos fragmentos, en 1 a 3 frases cortas, corrigiendo errores obvios de transcripción. "
    "Si es una pregunta, decí claramente qué se está preguntando. "
    "No sugieras respuestas ni qué decir: solo aclarás el significado."
)


# ------------------------------------------------------------------ websocket
@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    cfg = {"lang": "auto", "translate": False, "target": "es", "glossary": "", "save": False}
    history: list[dict] = []
    seq = 0
    send_lock = asyncio.Lock()
    log_path = TRANSCRIPTS / f"{datetime.now():%Y-%m-%d_%H%M%S}.jsonl"

    async def send(msg: dict):
        async with send_lock:
            await ws.send_text(json.dumps(msg, ensure_ascii=False))

    async def handle_segment(sid: int, audio: bytes, http: httpx.AsyncClient):
        try:
            res = await transcribe(http, audio, cfg["lang"])
        except Exception as e:  # noqa: BLE001 - se informa a la UI
            await send({"type": "error", "id": sid, "message": f"Transcripción: {e}"})
            return
        if not res["text"]:
            await send({"type": "empty", "id": sid})
            return
        item = {"id": sid, "t": datetime.now().isoformat(timespec="seconds"), **res}
        history.append(item)
        await send({"type": "caption", **item})
        if cfg["save"]:
            TRANSCRIPTS.mkdir(exist_ok=True)
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
        if cfg["translate"]:
            target = "español" if cfg["target"] == "es" else "English"
            try:
                tr = await ask_claude(TRANSLATE_SYS + glossary_note(cfg["glossary"]),
                                      f"Traducí al {target}:\n{res['text']}")
                await send({"type": "translation", "id": sid, "text": tr})
            except Exception as e:  # noqa: BLE001
                await send({"type": "error", "id": sid, "message": f"Traducción: {e}"})

    async def handle_explain(target: str):
        recent = history[-4:]
        if not recent:
            await send({"type": "explanation", "text": "Todavía no hay nada transcrito."})
            return
        lang = "español" if target == "es" else "English"
        text = "\n".join(f"- {h['text']}" for h in recent)
        try:
            out = await ask_claude(EXPLAIN_SYS + glossary_note(cfg["glossary"]),
                                   f"Respondé en {lang}. Últimos fragmentos (el último es el más reciente):\n{text}")
            await send({"type": "explanation", "text": out})
        except Exception as e:  # noqa: BLE001
            await send({"type": "error", "message": f"Explicación: {e}"})

    tasks: set[asyncio.Task] = set()

    def spawn(coro):
        t = asyncio.create_task(coro)
        tasks.add(t)
        t.add_done_callback(tasks.discard)

    async with httpx.AsyncClient(timeout=60) as http:
        try:
            while True:
                msg = await ws.receive()
                if msg.get("type") == "websocket.disconnect":
                    break
                if msg.get("bytes") is not None:
                    if not ELEVEN_KEY:
                        await send({"type": "error", "message": "Falta ELEVENLABS_API_KEY en live-captions/.env"})
                        continue
                    if len(msg["bytes"]) < 1500:
                        continue
                    seq += 1
                    await send({"type": "pending", "id": seq})
                    spawn(handle_segment(seq, msg["bytes"], http))
                elif msg.get("text"):
                    data = json.loads(msg["text"])
                    if data.get("type") == "config":
                        for k in cfg:
                            if k in data:
                                cfg[k] = data[k]
                    elif data.get("type") == "explain":
                        spawn(handle_explain(data.get("target", "es")))
                    elif data.get("type") == "clear":
                        history.clear()
        except WebSocketDisconnect:
            pass
        finally:
            for t in list(tasks):
                t.cancel()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8001)
