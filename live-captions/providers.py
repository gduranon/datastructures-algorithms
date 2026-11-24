"""Proveedores de IA (voz a texto y LLM), elegidos con variables de entorno."""
from __future__ import annotations

import asyncio
import json
import os
import platform
import random
import shutil
import sys
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path

import anthropic
import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")


def env(name: str, default: str = "") -> str:
    return os.getenv(name, "").strip() or default


STT_PROVIDER = env("STT_PROVIDER", "elevenlabs").lower()
LLM_PROVIDER = env("LLM_PROVIDER", "anthropic").lower()
CLAUDE_MODEL = env("CLAUDE_MODEL", "claude-opus-5-5")
CLAUDE_EFFORT = env("CLAUDE_EFFORT", "low")
OPENAI_URL = env("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
OPENAI_KEY = env("OPENAI_API_KEY")
OPENAI_MODEL = env("OPENAI_MODEL")
OPENAI_STT_URL = env("OPENAI_STT_BASE_URL", OPENAI_URL).rstrip("/")
OPENAI_STT_KEY = env("OPENAI_STT_API_KEY", OPENAI_KEY)
OPENAI_STT_MODEL = env("OPENAI_STT_MODEL", "whisper-1")
ELEVEN_KEY = env("ELEVENLABS_API_KEY")
ELEVEN_MODEL = env("ELEVENLABS_STT_MODEL", "scribe_v1")

# código de la UI -> (ElevenLabs, OpenAI). Los dos inglés comparten código de idioma:
# el acento se comunica como pista al LLM (ver app.py).
LANG_CODES = {"en-US": ("eng", "en"), "en-IN": ("eng", "en"), "eng": ("eng", "en"), "spa": ("spa", "es")}
LANG_NAMES = {"eng": "inglés", "en": "inglés", "english": "inglés",
              "spa": "español", "es": "español", "spanish": "español"}


def config_errors(stt: str = "") -> list[str]:
    errors = []
    provider = stt or STT_PROVIDER
    if provider == "macos":
        if not macos_available():
            errors.append("La voz de macOS necesita macOS 26 o posterior y las herramientas de Xcode (swiftc)")
    elif provider not in ("elevenlabs", "openai"):
        errors.append(f"STT_PROVIDER desconocido: {STT_PROVIDER}")
    elif provider == "elevenlabs" and not ELEVEN_KEY:
        errors.append("Falta ELEVENLABS_API_KEY en live-captions/.env")
    elif provider == "openai" and not OPENAI_STT_KEY and "api.openai.com" in OPENAI_STT_URL:
        errors.append("Falta OPENAI_API_KEY u OPENAI_STT_API_KEY en live-captions/.env")
    if LLM_PROVIDER not in ("anthropic", "openai"):
        errors.append(f"LLM_PROVIDER desconocido: {LLM_PROVIDER}")
    elif LLM_PROVIDER == "openai":
        if not OPENAI_MODEL:
            errors.append("Falta OPENAI_MODEL en live-captions/.env")
        if not OPENAI_KEY and "api.openai.com" in OPENAI_URL:
            errors.append("Falta OPENAI_API_KEY en live-captions/.env")
    # Anthropic puede autenticarse también con `ant auth login`, sin clave en .env.
    return errors


def _auth(key: str) -> dict:
    return {"Authorization": f"Bearer {key}"} if key else {}


# ---------------------------------------------------------------- voz a texto
STT_RETRY = {429, 500, 502, 503, 504}
STT_WAITS = (0.5, 1, 2, 4)
_stt_slots = asyncio.Semaphore(3)  # limita los pedidos simultáneos para no provocar más 429


async def _post_stt(http: httpx.AsyncClient, url: str, **kw) -> httpx.Response:
    """Reintenta con espera creciente cuando el proveedor está saturado."""
    for wait in (*STT_WAITS, None):
        async with _stt_slots:
            r = await http.post(url, **kw)
        if r.status_code not in STT_RETRY or "insufficient_quota" in r.text or wait is None:
            return r
        await asyncio.sleep(wait * random.uniform(0.8, 1.3))


MACOS_SRC = Path(__file__).parent / "macos_stt.swift"
MACOS_BIN = Path(__file__).parent / "models" / "macos_stt"
MACOS_LOCALES = {"en-US": "en-US", "en-IN": "en-IN", "eng": "en-US,en-IN", "spa": "es-US"}
_macos_build = asyncio.Lock()
_macos_slots = asyncio.Semaphore(3)  # aparte: la Mac no espera a los pedidos de red


def macos_available() -> bool:
    if sys.platform != "darwin" or int(platform.mac_ver()[0].split(".")[0] or 0) < 26:
        return False
    return MACOS_BIN.exists() or shutil.which("swiftc") is not None


async def _run(*cmd: str, timeout: float) -> bytes:
    p = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        out, err = await asyncio.wait_for(p.communicate(), timeout)
    except asyncio.TimeoutError:
        raise RuntimeError("macOS: se agotó el tiempo de espera") from None
    finally:
        if p.returncode is None:
            p.kill()
    if p.returncode:
        raise RuntimeError(f"macOS: {err.decode(errors='replace').strip()[-300:]}")
    return out


async def build_macos():
    """Compila macos_stt.swift la primera vez y cuando cambia."""
    async with _macos_build:
        if MACOS_BIN.exists() and MACOS_BIN.stat().st_mtime >= MACOS_SRC.stat().st_mtime:
            return
        MACOS_BIN.parent.mkdir(exist_ok=True)
        tmp = f"{MACOS_BIN}.tmp"
        await _run("xcrun", "swiftc", "-parse-as-library", "-O", str(MACOS_SRC), "-o", tmp, timeout=180)
        os.replace(tmp, MACOS_BIN)


async def _transcribe_macos(audio: bytes, lang: str, glossary: str) -> dict:
    if audio[:4] != b"RIFF":
        raise RuntimeError("macOS: el navegador no pudo convertir el audio a WAV")
    await build_macos()
    with tempfile.NamedTemporaryFile(suffix=".wav") as f:  # se borra al terminar
        f.write(audio)
        f.flush()
        async with _macos_slots:
            # La primera vez puede descargar el modelo de un idioma.
            out = await _run(str(MACOS_BIN), f.name, MACOS_LOCALES.get(lang, "en-US,en-IN,es-US"), glossary, timeout=120)
    j = json.loads(out)
    code = j["language"][:2]
    return {"text": j["text"], "language": LANG_NAMES.get(code, code),
            "confidence": j["confidence"]}


async def transcribe(http: httpx.AsyncClient, audio: bytes, lang: str, glossary: str = "", stt: str = "") -> dict:
    if (stt or STT_PROVIDER) == "macos":
        return await _transcribe_macos(audio, lang, glossary)
    codes = LANG_CODES.get(lang)
    # Safari graba mp4; Chrome, Edge y Firefox, webm (u ogg).
    if audio[:4] == b"RIFF":
        file = ("segment.wav", audio, "audio/wav")
    elif audio[4:8] == b"ftyp":
        file = ("segment.mp4", audio, "audio/mp4")
    elif audio[:4] == b"OggS":
        file = ("segment.ogg", audio, "audio/ogg")
    else:
        file = ("segment.webm", audio, "audio/webm")
    if STT_PROVIDER == "elevenlabs":
        form = {"model_id": ELEVEN_MODEL, "tag_audio_events": "false"}
        if codes:
            form["language_code"] = codes[0]
        r = await _post_stt(http, "https://api.elevenlabs.io/v1/speech-to-text",
                            headers={"xi-api-key": ELEVEN_KEY}, data=form, files={"file": file})
        key = "language_code"
    else:
        form = {"model": OPENAI_STT_MODEL,
                "response_format": "verbose_json" if "whisper" in OPENAI_STT_MODEL else "json"}
        if codes:
            form["language"] = codes[1]
        if glossary:
            form["prompt"] = glossary
        r = await _post_stt(http, f"{OPENAI_STT_URL}/audio/transcriptions",
                            headers=_auth(OPENAI_STT_KEY), data=form, files={"file": file})
        key = "language"
    if r.status_code in STT_RETRY:
        raise RuntimeError(f"{STT_PROVIDER} está saturado o sin cupo ({r.status_code}) y se perdió una frase. {r.text[:200]}")
    if r.status_code != 200:
        raise RuntimeError(f"{STT_PROVIDER} {r.status_code}: {r.text[:200]}")
    j = r.json()
    code = j.get(key) or (codes and codes[1])
    return {"text": (j.get("text") or "").strip(), "language": LANG_NAMES.get(code, code)}


# ------------------------------------------------------------------------ LLM
_claude: anthropic.AsyncAnthropic | None = None


async def _stream_claude(system: str, user: str) -> AsyncIterator[str]:
    global _claude
    if _claude is None:
        _claude = anthropic.AsyncAnthropic(timeout=60)
    extra = {}
    if not CLAUDE_MODEL.startswith("claude-haiku"):  # Haiku no admite fallback del servidor
        extra = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
    async with _claude.beta.messages.stream(
        model=CLAUDE_MODEL, max_tokens=8000, system=system,
        thinking={"type": "adaptive"}, output_config={"effort": CLAUDE_EFFORT},
        messages=[{"role": "user", "content": user}], **extra,
    ) as s:
        async for text in s.text_stream:
            yield text
        final = await s.get_final_message()
    if final.stop_reason == "refusal":
        raise RuntimeError("El modelo no procesó este texto.")
    if final.stop_reason == "max_tokens":
        raise RuntimeError("La respuesta quedó cortada por longitud.")


async def _stream_openai(http: httpx.AsyncClient, system: str, user: str) -> AsyncIterator[str]:
    body = {"model": OPENAI_MODEL, "stream": True,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    async with http.stream("POST", f"{OPENAI_URL}/chat/completions",
                           headers=_auth(OPENAI_KEY), json=body) as r:
        if r.status_code != 200:
            raise RuntimeError(f"LLM {r.status_code}: {(await r.aread())[:200].decode(errors='replace')}")
        async for line in r.aiter_lines():
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                return
            chunk = json.loads(data)
            if chunk.get("error"):
                raise RuntimeError(f"LLM: {str(chunk['error'])[:200]}")
            for choice in chunk.get("choices") or []:
                if text := (choice.get("delta") or {}).get("content"):
                    yield text


async def stream_llm(http: httpx.AsyncClient, system: str, user: str) -> AsyncIterator[str]:
    if LLM_PROVIDER not in ("anthropic", "openai"):
        raise RuntimeError(f"LLM_PROVIDER desconocido: {LLM_PROVIDER}")
    gen = _stream_claude(system, user) if LLM_PROVIDER == "anthropic" else _stream_openai(http, system, user)
    async for text in gen:
        yield text


async def ask_llm(http: httpx.AsyncClient, system: str, user: str) -> str:
    return "".join([t async for t in stream_llm(http, system, user)]).strip()
