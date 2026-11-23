"""Pruebas de api.py SIN Ollama: se sustituye conversar() y urlopen()."""
import io
import json

import pytest
from fastapi.testclient import TestClient

import api

cliente = TestClient(api.app)


def test_chat_ok_cumple_el_contrato(monkeypatch):
    monkeypatch.setattr(api, "conversar", lambda q, s=None: f"respuesta a: {q}")
    r = cliente.post("/api/v1/chat", json={"question": "hola", "sessionId": "abc"})
    assert r.status_code == 200
    cuerpo = r.json()
    assert set(cuerpo) == {"requestId", "answer", "elapsedMs", "status"}
    assert cuerpo["answer"] == "respuesta a: hola" and cuerpo["status"] == "ok"
    assert isinstance(cuerpo["elapsedMs"], int) and len(cuerpo["requestId"]) == 36


def test_chat_sin_session_id(monkeypatch):
    monkeypatch.setattr(api, "conversar", lambda q, s=None: "ok")
    assert cliente.post("/api/v1/chat", json={"question": "hola"}).status_code == 200


@pytest.mark.parametrize("respuesta", ["", "   "])
def test_chat_respuesta_vacia_devuelve_502(monkeypatch, respuesta):
    monkeypatch.setattr(api, "conversar", lambda q, s=None: respuesta)
    r = cliente.post("/api/v1/chat", json={"question": "hola"})
    assert r.status_code == 502 and r.json()["status"] == "error"


def test_chat_si_el_grafo_falla_devuelve_502_con_el_mismo_contrato(monkeypatch):
    def falla(_q, _s=None):
        raise ConnectionError("Ollama apagado")
    monkeypatch.setattr(api, "conversar", falla)
    r = cliente.post("/api/v1/chat", json={"question": "hola"})
    assert r.status_code == 502
    assert set(r.json()) == {"requestId", "answer", "elapsedMs", "status"} and r.json()["answer"] == ""


@pytest.mark.parametrize("cuerpo", [{}, {"question": ""}])
def test_chat_valida_la_pregunta(cuerpo):
    assert cliente.post("/api/v1/chat", json=cuerpo).status_code == 422


def test_health_ok(monkeypatch):
    tags = {"models": [{"name": "qwen2.5:3b"}]}
    monkeypatch.setattr(api.urllib.request, "urlopen",
                        lambda url, timeout: io.BytesIO(json.dumps(tags).encode()))
    r = cliente.get("/health/llm")
    assert r.status_code == 200
    assert r.json()["ok"] is True and r.json()["result"] == tags
    assert r.json()["endpoint"].endswith("/api/tags")


def test_health_error(monkeypatch):
    def falla(url, timeout):
        raise OSError("connection refused")
    monkeypatch.setattr(api.urllib.request, "urlopen", falla)
    r = cliente.get("/health/llm")
    assert r.status_code == 502 and r.json()["ok"] is False


def test_cors_permite_el_frontend_del_curso():
    r = cliente.options("/api/v1/chat", headers={"Origin": "http://localhost:4200",
                                                 "Access-Control-Request-Method": "POST",
                                                 "Access-Control-Request-Headers": "content-type"})
    assert r.headers["access-control-allow-origin"] == "http://localhost:4200"


def test_chat_pasa_el_session_id_al_grafo(monkeypatch):
    recibido = {}

    def falso(pregunta, sesion=None):
        recibido.update(pregunta=pregunta, sesion=sesion)
        return "ok"
    monkeypatch.setattr(api, "conversar", falso)
    cliente.post("/api/v1/chat", json={"question": "sí", "sessionId": "abc"})
    assert recibido == {"pregunta": "sí", "sesion": "abc"}


def test_chat_con_confirmacion_de_reserva_de_punta_a_punta(monkeypatch):
    """Dos peticiones HTTP con el mismo sessionId: la 1.ª pide confirmación, la 2.ª ('sí') reserva."""
    import grafo
    from langgraph.checkpoint.memory import InMemorySaver
    from tests.test_grafo import PREGUNTA_4, SintetizadorFalso, SupervisorFalso, nodo_falso

    llamados = []
    monkeypatch.setattr(grafo, "CONFIRMAR_RESERVAS", True)
    monkeypatch.setattr(grafo, "modelo_supervisor", SupervisorFalso(["clima", "presupuesto", "reservas"]))
    monkeypatch.setattr(grafo, "modelo_sintetizador", SintetizadorFalso())
    for n in ("clima", "presupuesto", "reservas"):
        monkeypatch.setattr(grafo, f"nodo_{n}", nodo_falso(n, llamados))
    monkeypatch.setattr(grafo, "app", grafo.construir_grafo(InMemorySaver()))
    grafo._PENDIENTES.clear()

    r1 = cliente.post("/api/v1/chat", json={"question": PREGUNTA_4, "sessionId": "s1"}).json()
    assert r1["status"] == "ok" and "¿Confirmas la reserva?" in r1["answer"]
    assert "reservas" not in llamados
    r2 = cliente.post("/api/v1/chat", json={"question": "sí", "sessionId": "s1"}).json()
    assert r2["status"] == "ok" and r2["answer"].startswith("RESPUESTA FINAL")
    assert llamados[-1] == "reservas"
