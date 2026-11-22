"""Pruebas del grafo SIN Ollama: se reemplazan el supervisor, los especialistas y el sintetizador
por dobles de prueba para verificar el enrutamiento, los reducers y los límites de autonomía."""
import pytest

import grafo
from grafo import Decision


class SupervisorFalso:
    """Devuelve las decisiones de una lista, en orden. Si un elemento es Exception, la lanza."""
    def __init__(self, decisiones):
        self.decisiones = list(decisiones)
        self.llamadas = 0

    def invoke(self, _mensajes):
        self.llamadas += 1
        d = self.decisiones.pop(0)
        if isinstance(d, Exception):
            raise d
        return Decision(siguiente=d, motivo="prueba")


class SintetizadorFalso:
    def __init__(self):
        self.mensajes = None

    def invoke(self, mensajes):
        self.mensajes = mensajes
        return type("Resp", (), {"content": "RESPUESTA FINAL"})()


def nodo_falso(nombre, llamados):
    def nodo(_estado):
        llamados.append(nombre)
        return {"resultados": [f"[{nombre}] listo"], "consultados": [nombre]}
    return nodo


@pytest.fixture
def montar(monkeypatch):
    """Construye un grafo con dobles. Devuelve (grafo_compilado, llamados, sintetizador)."""
    def _montar(decisiones):
        llamados = []
        sint = SintetizadorFalso()
        monkeypatch.setattr(grafo, "modelo_supervisor", SupervisorFalso(decisiones))
        monkeypatch.setattr(grafo, "modelo_sintetizador", sint)
        for n in ("clima", "presupuesto", "reservas"):
            monkeypatch.setattr(grafo, f"nodo_{n}", nodo_falso(n, llamados))
        return grafo.construir_grafo(), llamados, sint
    return _montar


def test_pregunta_3_clima_y_presupuesto(montar):
    app, llamados, _ = montar(["clima", "presupuesto", "fin"])
    estado = app.invoke(grafo.estado_inicial("pregunta"))
    assert llamados == ["clima", "presupuesto"]
    assert estado["consultados"] == ["clima", "presupuesto"]          # el reducer acumula
    assert len(estado["resultados"]) == 2
    assert estado["respuesta_final"] == "RESPUESTA FINAL"


def test_pregunta_4_tres_especialistas_y_limite_de_autonomia(montar):
    # El supervisor "quisiera" seguir, pero tras 3 especialistas se corta sin preguntarle.
    app, llamados, _ = montar(["clima", "presupuesto", "reservas"])
    estado = app.invoke(grafo.estado_inicial("pregunta"))
    assert llamados == ["clima", "presupuesto", "reservas"]
    assert estado["respuesta_final"] == "RESPUESTA FINAL"


def test_limite_configurable(montar, monkeypatch):
    monkeypatch.setattr(grafo, "MAX_PASOS", 1)
    app, llamados, _ = montar(["clima", "presupuesto"])
    app.invoke(grafo.estado_inicial("pregunta"))
    assert llamados == ["clima"]


def test_pregunta_6_fuera_de_tema_no_llama_especialistas(montar):
    app, llamados, sint = montar(["fin"])
    estado = app.invoke(grafo.estado_inicial("¿Quién ganó el mundial de 2022?"))
    assert llamados == []
    assert estado["respuesta_final"] == "RESPUESTA FINAL"
    assert "todavía no hay resultados" in sint.mensajes[1][1]


def test_no_repite_especialistas(montar):
    app, llamados, _ = montar(["clima", "clima"])
    estado = app.invoke(grafo.estado_inicial("pregunta"))
    assert llamados == ["clima"]
    assert estado["consultados"] == ["clima"]


def test_decision_invalida_finaliza_de_forma_segura(montar):
    app, llamados, _ = montar([ValueError("JSON inválido")])
    estado = app.invoke(grafo.estado_inicial("pregunta"))
    assert llamados == []
    assert estado["respuesta_final"] == "RESPUESTA FINAL"


def test_sintetizador_recibe_los_resultados(montar):
    app, _, sint = montar(["presupuesto", "fin"])
    app.invoke(grafo.estado_inicial("¿Nos alcanza?"))
    texto = sint.mensajes[1][1]
    assert "¿Nos alcanza?" in texto and "[presupuesto] listo" in texto


def test_decision_solo_acepta_valores_permitidos():
    with pytest.raises(Exception):
        Decision(siguiente="actividades", motivo="x")


def test_nodo_especialista_envuelve_un_agente():
    class AgenteFalso:
        def invoke(self, entrada):
            assert "Pregunta del usuario: hola" in entrada["messages"][0]["content"]
            return {"messages": [type("M", (), {"content": "respuesta del agente"})()]}

    nodo = grafo.crear_nodo_especialista("clima", AgenteFalso())
    salida = nodo(grafo.estado_inicial("hola"))
    assert salida == {"resultados": ["[clima] respuesta del agente"], "consultados": ["clima"]}


def test_mermaid_contiene_los_cinco_nodos():
    texto = grafo.app.get_graph().draw_mermaid()
    for nodo in ("supervisor", "clima", "presupuesto", "reservas", "sintetizador"):
        assert nodo in texto
