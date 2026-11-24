"""python test_app.py  (sin red: proveedores simulados)"""
import asyncio
import app as A
from fastapi.testclient import TestClient

texts = ["hello everyone", "what is RAG?"] + [f"line {i}" for i in range(8)]
n = 0
async def stt(http, audio, lang, glossary="", stt=""):
    global n
    n += 1
    return {"text": texts[n - 1], "language": "inglés"}
async def llm(http, system, user):
    if system.startswith(A.SUMMARY_SYS): out = ["resumen"]
    elif system.startswith(A.SCORE_SYS):
        assert "DESCRIPCIÓN DEL ROL" in user and "Arquitecto" in user and "R sugerida" not in user
        out = ['```json\n{"summary": "ok", "criteria": {"rol": {"score": 3}, "tecnica": {"score": 9}, "claridad": null}, ', '"questions": [{"question": "q", "score": "x"}, 5]}\n```']
    elif system.startswith(A.ASK_SYS):
        # todo lo transcrito (aunque ya esté resumido) y las preguntas previas
        assert all(t in user for t in texts[:7]) and "R sugerida: Retrieval" in user and "R completa: largo detalle" in user
        assert "ESQUEMA" not in user and "SIGLAS" not in user and "mi pregunta\nR sugerida" not in user
        out = ["- uno\n", "- dos"]
    elif system.startswith(A.EXPAND_SYS):
        assert "what is RAG?" in user
        out = ["largo ", "detalle\nSIGLAS: RAG=Retrieval-Augmented Generation\nESQUEMA: flujo\nN a|Pregunta\nN b|Respuesta\nE a>b"]
    elif "what is RAG?" in user.split("FRASES NUEVAS")[1]: out = ["L 2|P", "|-|RAG\n", "Q", ": What is RAG?", "\nA", ": Retrie", "val"]
    else:
        import re
        out = [f"L {i}|R|2|Costos\n" for i in re.findall(r"^#(\d+)", user.split("FRASES NUEVAS")[1], re.M)] + ["NO"]
    for o in out:
        await asyncio.sleep(0)
        yield o
A.providers.transcribe, A.providers.stream_llm = stt, llm
A.providers.macos_available = lambda: False
A.providers.config_errors = lambda stt="": []
A.CONTEXT_SEGMENTS = 4
import tempfile
from pathlib import Path
A.TRANSCRIPTS = Path(tempfile.mkdtemp())  # nunca tocar las transcripciones reales
(A.TRANSCRIPTS / "a.jsonl").write_text("{}"); (A.TRANSCRIPTS / "otro.txt").write_text("x")
KEY = "x" * 20

def until(ws, f):
    seen = []
    while True:
        seen.append(ws.receive_json())
        if f(seen[-1]): return seen

with TestClient(A.app) as c:
    assert c.get("/").status_code == c.get("/api/config").status_code == 200
    with c.websocket_connect(f"/ws?session={KEY}") as ws:
        ws.receive_json()
        ws.send_bytes(b"0" * 2000); until(ws, lambda m: m["type"] == "caption")
        ws.send_bytes(b"0" * 2000)
        seen = until(ws, lambda m: m["type"] == "answer" and m["done"])
        assert seen[-1]["text"] == "Retrieval"
        assert any(m["type"] == "answer" and not m["done"] for m in seen)
        assert any(m["type"] == "label" and m["id"] == 2 and m["kind"] == "P" and m["topic"] == "RAG" for m in seen)
        assert until(ws, lambda m: m["type"] == "detail" and m["done"])[-1]["text"].startswith("largo detalle\nSIGLAS: RAG=")
    with c.websocket_connect(f"/ws?session={KEY}") as ws:  # reconexión
        h = ws.receive_json()
        assert len(h["captions"]) == 2 and h["questions"][0]["detail"].startswith("largo detalle")
        for _ in range(5):
            ws.send_bytes(b"0" * 2000); until(ws, lambda m: m["type"] == "caption")
        ws.send_json({"type": "config", "role": "Arquitecto"})
        ws.send_json({"type": "assess"})
        a = until(ws, lambda m: m["type"] == "assessment")[-1]["data"]
        assert a["score"] == 75 and a["criteria"][1]["score"] == 5 and a["questions"] == [dict(score=None, question="q", answer="", good="", improve="")]
        d = A.TRANSCRIPTS / "interviews" / A.sessions[KEY].interview_name
        read = lambda n: [x["text"] for x in A.json.loads((d / n).read_text())]
        assert read("interviewer_questions.json") == ["what is RAG?"] and read("interviewee_answers.json")[-1] == texts[6]
        assert (d / "role.txt").read_text() == "Arquitecto" and (d / "assessment.json").exists()
        ws.send_json({"type": "ask", "text": " mi  pregunta "})
        seen = until(ws, lambda m: m["type"] == "detail" and m["done"])
        assert any(m["type"] == "question" and m["question"] == "mi pregunta" for m in seen)
        assert any(m["type"] == "answer" and m["done"] and m["text"] == "- uno\n- dos" for m in seen)
        ws.send_json({"type": "explain"}); until(ws, lambda m: m["type"] == "explanation" or m["type"] == "error")
        assert A.sessions[KEY].summary == "resumen"
        with c.websocket_connect("/ws?session=" + "y" * 20) as w2:  # como al reiniciar la app
            old = w2.receive_json()["questions"]
            assert [(q["question"], q["old"]) for q in old] == [("What is RAG?", True), ("mi pregunta", True)]
            assert "ESQUEMA: flujo" in old[0]["detail"] and len({q["id"] for q in old}) == 2
            s2 = A.sessions["y" * 20]
            assert s2.seq == 2 and s2.qa() == ""
        ws.send_json({"type": "clear"})
        assert until(ws, lambda m: m["type"] == "history")[-1]["captions"] == []
        assert len(A.sessions[KEY].questions) == 2 and len(A.load_questions()) == 2
        logs = [f for f in A.TRANSCRIPTS.glob("*.jsonl") if f.name != "a.jsonl"]
        assert len(logs) == 1 and [A.json.loads(l)["text"] for l in logs[0].read_text().splitlines()] == texts[:7]
        ws.send_json({"type": "delete_transcripts"})
        assert until(ws, lambda m: m["type"] == "transcripts_deleted")[-1]["count"] == 7
        assert A.sessions[KEY].questions == []
        assert [f.name for f in A.TRANSCRIPTS.iterdir()] == ["otro.txt"]
    try:
        with c.websocket_connect(f"/ws?session={KEY}", headers={"origin": "https://evil.example"}): raise SystemExit("origen aceptado")
    except A.WebSocketDisconnect: pass
# ---- quién preguntó y quién respondió, con voces
s = A.Session()
s.speakers.items = {1: {"name": "E", "me": False}, 2: {"name": "Yo", "me": True}}
s.speakers.label = lambda i: str(i)
H = lambda i, sp, k, alt=None: {"id": i, "t": "", "speaker": sp, "kind": k, "reply_to": None, "text": str(i), "alt_of": alt, "topic": ""}
s.history = [H(1, 1, "P"), H(2, 2, "R"), H(3, 2, "O"), H(4, 2, "P"), H(5, 1, "R"), H(6, 1, "P"), H(7, 1, "P", 6), H(8, None, "R")]
assert [[x["id"] for x in l] for l in s.interview()] == [[1, 7], [2, 3, 8]]
try: A.parse_assessment("no"); raise SystemExit("aceptó basura")
except RuntimeError: pass
# ---- carrera macOS / motor remoto: (espera, texto o error, confianza)
A.providers.macos_available = lambda: True
A.MACOS_MAX_WAIT = .15
def race(main, mac):
    async def rec(http, audio, lang, glossary="", stt=""):
        wait, text, conf = mac if stt == "macos" else main
        await asyncio.sleep(wait)
        if text is None: raise RuntimeError("429")
        return {"text": text, "language": "inglés", **({"confidence": conf} if stt == "macos" else {})}
    A.providers.transcribe = rec
    async def go():
        s = A.Session(); s.cfg.update(diarize=False, suggest=False, classify=False); s.seq = 1; out = []
        async def send(m): out.append(m)
        s.send = send
        await s.handle_segment(1, b"")
        return [(m["source"], m["text"], m["alt_of"]) for m in out if m["type"] == "caption"], [m["type"] for m in out]
    return asyncio.run(go())
E, M = A.providers.STT_PROVIDER, "macos"
assert race((.05, "Handled a", 1), (0, "handle the", .95))[0] == [(M, "handle the", None), (E, "Handled a", 1)]
assert race((.05, "¿Cómo?", 1), (0, "como", .95))[0] == [(M, "como", None)]
assert race((.05, "bien", 1), (0, "mal", .5))[0] == [(E, "bien", None)]
assert race((.4, "bien", 1), (0, "mal", .5))[0] == [(M, "mal", None), (E, "bien", 1)]
assert race((0, "bien", 1), (.05, "otra", .99))[0] == [(E, "bien", None)]
assert race((0, None, 1), (.05, "respaldo", .5)) == ([(M, "respaldo", None)], ["caption", "error"])
assert race((.05, "bien", 1), (0, None, 0)) == ([(E, "bien", None)], ["caption"])
assert race((.05, "bien", 1), (0, "", 0))[0] == [(E, "bien", None)]
assert race((0, None, 1), (.05, None, 0)) == ([], ["error"])
assert race((0, None, 1), (.05, "", 0)) == ([], ["empty", "error"])
assert A.parse_answer("NO") is None
assert A.parse_labels("L 3|R|#2|Costos\nL 4|P|-|-\nQ: x\nL 5|P|-|z\n") == [(3, "R", 2, "Costos"), (4, "P", None, "")]
if A.voices_available():
    import numpy as np
    S = A.Speakers(); a, b = np.array([1., 0]), np.array([0, 1.])
    assert [S.assign((a, 2)), S.assign((b, 2)), S.assign((a, 2)), S.assign((-a, 1))] == [1, 2, 1, None]
    S.merge(2, 1); assert list(S.items) == [1]
print("OK")
