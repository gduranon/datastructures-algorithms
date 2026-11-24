"""Simulador de entrevista (AI Architect).

Flujo: la app muestra una pregunta, vos respondés hablando, la respuesta se transcribe
con ElevenLabs Speech-to-Text (detección automática de inglés US, inglés de India o español)
y Claude la evalúa con un feedback estructurado y una repregunta.

Ejecutar:  uvicorn app:app --reload   (o: python app.py)  ->  http://127.0.0.1:8000
"""
from __future__ import annotations

import json
import os
import random
from datetime import datetime
from pathlib import Path
from typing import Literal

import anthropic
import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

HERE = Path(__file__).parent
load_dotenv(HERE / ".env")

ELEVEN_KEY = os.getenv("ELEVENLABS_API_KEY", "")
ELEVEN_STT_MODEL = os.getenv("ELEVENLABS_STT_MODEL", "scribe_v1")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-opus-5-5")
ELEVEN_BASE = "https://api.elevenlabs.io/v1"

SESSIONS_DIR = HERE / "sessions"
SESSIONS_DIR.mkdir(exist_ok=True)

# ---------------------------------------------------------------- questions
def load_questions() -> list[dict]:
    out: list[dict] = []
    bank = HERE.parent / "quiz" / "quiz_questions.json"
    if bank.exists():
        for q in json.loads(bank.read_text(encoding="utf-8")):
            correct = next(o["text"] for o in q["options"] if o["id"] == q["correct_option_id"])
            out.append({
                "id": q["id"], "module": q["module_id"], "difficulty": q["difficulty"],
                "source": "banco", "text": {"es": q["stem"]},
                "reference": f"Idea correcta: {correct} Explicación: {q['explanation']}",
            })
    open_q = HERE / "questions_open.json"
    if open_q.exists():
        out.extend(json.loads(open_q.read_text(encoding="utf-8")))
    return out


QUESTIONS = load_questions()
QBY_ID = {q["id"]: q for q in QUESTIONS}

# ---------------------------------------------------------------- claude
claude = anthropic.Anthropic()  # ANTHROPIC_API_KEY o perfil de `ant auth login`

FEEDBACK_SCHEMA = {
    "type": "object",
    "properties": {
        "score": {"type": "integer", "description": "1 (muy débil) a 5 (excelente)"},
        "verdict": {"type": "string", "description": "Una frase de resumen"},
        "covered": {"type": "array", "items": {"type": "string"}},
        "missing": {"type": "array", "items": {"type": "string"}},
        "communication": {"type": "string", "description": "Estructura, claridad y concisión de la respuesta oral"},
        "model_answer": {"type": "string", "description": "Respuesta modelo de 60-90 segundos hablada"},
        "follow_up": {"type": "string", "description": "Repregunta que haría un entrevistador exigente"},
    },
    "required": ["score", "verdict", "covered", "missing", "communication", "model_answer", "follow_up"],
    "additionalProperties": False,
}

SYSTEM = (
    "Sos un entrevistador técnico senior evaluando a un candidato a AI Architect "
    "(agentes de IA sobre Azure, RAG, ITSM, RCA, AgentOps, seguridad, ROI, liderazgo de un equipo chico). "
    "Recibís la pregunta, una referencia opcional y la transcripción automática de la respuesta oral del candidato. "
    "El candidato puede responder en español o en inglés, con acento de EE. UU., de India o hispanohablante. "
    "La transcripción automática puede tener errores por el acento o el reconocimiento de voz: no penalices palabras mal transcritas "
    "ni el acento si la idea se entiende; evaluá contenido, estructura y claridad. "
    "Evaluá con rigor y sin inflar el puntaje: valorá trade-offs, seguridad, métricas, human-in-the-loop y cuándo NO usar un LLM. "
    "Si la respuesta está vacía o no responde la pregunta, decilo y puntuá 1. "
    "Escribí el feedback en el idioma indicado; la respuesta modelo debe sonar natural dicha en voz alta."
)


class Feedback(BaseModel):
    score: int
    verdict: str
    covered: list[str]
    missing: list[str]
    communication: str
    model_answer: str
    follow_up: str


def evaluate(question: str, reference: str | None, answer: str, lang: str, answer_lang: str) -> Feedback:
    user = (
        f"Idioma del feedback: {'español (Uruguay)' if lang == 'es' else 'English'}\n"
        f"Idioma detectado en la respuesta: {answer_lang or 'desconocido'}\n\n"
        f"<pregunta>{question}</pregunta>\n"
        + (f"<referencia>{reference}</referencia>\n" if reference else "")
        + f"<respuesta_transcrita>{answer}</respuesta_transcrita>"
    )
    try:
        resp = claude.beta.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=16000,
            system=SYSTEM,
            thinking={"type": "adaptive"},
            output_config={"effort": "medium", "format": {"type": "json_schema", "schema": FEEDBACK_SCHEMA}},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            messages=[{"role": "user", "content": user}],
        )
    except anthropic.AuthenticationError:
        raise HTTPException(500, "Claude: API key inválida o ausente (ANTHROPIC_API_KEY).")
    except anthropic.RateLimitError:
        raise HTTPException(429, "Claude: límite de uso alcanzado, probá en un minuto.")
    except anthropic.APIStatusError as e:
        raise HTTPException(502, f"Claude: error {e.status_code}: {e.message}")
    except anthropic.APIConnectionError:
        raise HTTPException(502, "Claude: sin conexión.")

    if resp.stop_reason == "refusal":
        raise HTTPException(502, "Claude no pudo evaluar esta respuesta.")
    text = next((b.text for b in resp.content if b.type == "text"), "")
    try:
        return Feedback.model_validate_json(text)
    except ValueError:
        raise HTTPException(502, "Claude devolvió un formato inesperado; intentá de nuevo.")


# ---------------------------------------------------------------- app
app = FastAPI(title="Simulador de entrevista")


def need_eleven():
    if not ELEVEN_KEY:
        raise HTTPException(500, "Falta ELEVENLABS_API_KEY en interview-sim/.env")


@app.get("/")
def index():
    return FileResponse(HERE / "static" / "index.html")


@app.get("/api/config")
def config():
    return {
        "elevenlabs": bool(ELEVEN_KEY),
        "claude_model": CLAUDE_MODEL,
        "questions": len(QUESTIONS),
        "modules": sorted({q["module"] for q in QUESTIONS}),
    }


@app.get("/api/question")
def question(source: Literal["all", "banco", "abierta"] = "all", module: str = "", lang: str = "es",
             exclude: str = ""):
    skip = set(filter(None, exclude.split(",")))
    pool = [q for q in QUESTIONS
            if (source == "all" or q["source"] == source)
            and (not module or q["module"] == module)
            and q["id"] not in skip]
    if not pool:
        raise HTTPException(404, "No quedan preguntas con ese filtro.")
    q = random.choice(pool)
    return {"id": q["id"], "module": q["module"], "difficulty": q["difficulty"], "source": q["source"],
            "text": q["text"].get(lang) or q["text"]["es"]}


# "auto" deja que Scribe detecte el idioma: cubre inglés US, inglés de India y español
# en la misma sesión. Forzar "eng" o "spa" ayuda si la detección se confunde en respuestas cortas.
STT_LANGS = {"auto": None, "eng": "eng", "spa": "spa"}
LANG_NAMES = {"eng": "inglés", "en": "inglés", "spa": "español", "es": "español"}


@app.post("/api/stt")
async def stt(audio: UploadFile = File(...), stt_lang: str = Form("auto")):
    need_eleven()
    data = await audio.read()
    if len(data) < 2000:
        return {"text": "", "language": None, "probability": None}
    form = {"model_id": ELEVEN_STT_MODEL, "tag_audio_events": "false"}
    if STT_LANGS.get(stt_lang):
        form["language_code"] = STT_LANGS[stt_lang]
    async with httpx.AsyncClient(timeout=120) as http:
        r = await http.post(
            f"{ELEVEN_BASE}/speech-to-text",
            headers={"xi-api-key": ELEVEN_KEY},
            data=form,
            files={"file": (audio.filename or "answer.webm", data, audio.content_type or "audio/webm")},
        )
    if r.status_code != 200:
        raise HTTPException(502, f"ElevenLabs STT {r.status_code}: {r.text[:300]}")
    j = r.json()
    code = j.get("language_code")
    return {"text": j.get("text", "").strip(), "language": LANG_NAMES.get(code, code),
            "probability": j.get("language_probability")}


class EvalIn(BaseModel):
    question_id: str
    question: str
    answer: str
    lang: str = "es"
    answer_lang: str = ""
    is_follow_up: bool = False


@app.post("/api/evaluate")
def evaluate_ep(body: EvalIn):
    q = QBY_ID.get(body.question_id)
    reference = None if body.is_follow_up or not q else q.get("reference")
    fb = evaluate(body.question, reference, body.answer, body.lang, body.answer_lang)
    record = {"t": datetime.now().isoformat(timespec="seconds"), **body.model_dump(), "feedback": fb.model_dump()}
    with open(SESSIONS_DIR / f"{datetime.now():%Y-%m-%d}.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return fb


@app.get("/api/history")
def history(limit: int = 30):
    rows = []
    for p in sorted(SESSIONS_DIR.glob("*.jsonl"), reverse=True):
        for line in reversed(p.read_text(encoding="utf-8").splitlines()):
            rows.append(json.loads(line))
            if len(rows) >= limit:
                return rows
    return rows


app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
