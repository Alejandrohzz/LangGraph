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

    def invoke(self, mensajes):
        self.ultimo = mensajes[1][1]
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
        monkeypatch.setattr(grafo, "MOSTRAR_DATOS_VERIFICADOS", False)
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
    estado = app.invoke(grafo.estado_inicial("Si nos alcanza, reserva Suesca a nombre de Laura"))
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


def test_nodo_especialista_guarda_los_datos_de_las_herramientas():
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

    class AgenteConTools:
        def invoke(self, _entrada):
            return {"messages": [
                HumanMessage(content="pregunta"),
                AIMessage(content="", tool_calls=[{"name": "consultar_pronostico", "args": {}, "id": "1"}]),
                ToolMessage(content="Villa de Leyva el sabado: soleado, lluvia 5 %.", tool_call_id="1"),
                ToolMessage(content="Error invoking tool: Field required", tool_call_id="2", status="error"),
                AIMessage(content="No hay mucha probabilidad de lluvia. El costo es gratis."),
            ]}

    salida = grafo.crear_nodo_especialista("clima", AgenteConTools())(grafo.estado_inicial("x"))
    assert salida["resultados"] == ["[clima] Villa de Leyva el sabado: soleado, lluvia 5 %."]
    assert salida["consultados"] == ["clima"]


def test_supervisor_ve_que_agentes_le_quedan(montar):
    app, _, _ = montar(["clima", "fin"])
    app.invoke(grafo.estado_inicial("pregunta"))
    assert "todavía puedes elegir: presupuesto, reservas" in grafo.modelo_supervisor.ultimo


def test_no_llama_a_reservas_si_el_usuario_no_pidio_reservar(montar):
    app, llamados, _ = montar(["clima", "presupuesto", "reservas"])
    estado = app.invoke(grafo.estado_inicial("¿Cómo estará el clima y cuánto cuesta?"))
    assert llamados == ["clima", "presupuesto"]
    assert estado["respuesta_final"] == "RESPUESTA FINAL"


def test_nodo_reservas_deja_claro_que_no_se_reservo():
    class AgenteSinReserva:
        def invoke(self, _entrada):
            from langchain_core.messages import AIMessage, ToolMessage
            return {"messages": [ToolMessage(content="Suesca el sabado: quedan 8 cupos.", tool_call_id="1"),
                                 AIMessage(content="Reservé todo")]}

    salida = grafo.crear_nodo_especialista("reservas", AgenteSinReserva())(grafo.estado_inicial("x"))
    assert "No se creó ninguna reserva." in salida["resultados"][0]
    assert "Reservé todo" not in salida["resultados"][0]


def test_no_reserva_si_el_presupuesto_no_alcanza(monkeypatch):
    llamados = []

    def presupuesto(_estado):
        llamados.append("presupuesto")
        return {"resultados": ["[presupuesto] No alcanza: presupuesto $150.000 - costo $210.000 = faltan $60.000."],
                "consultados": ["presupuesto"]}

    sint = SintetizadorFalso()
    monkeypatch.setattr(grafo, "modelo_supervisor", SupervisorFalso(["presupuesto", "reservas"]))
    monkeypatch.setattr(grafo, "modelo_sintetizador", sint)
    monkeypatch.setattr(grafo, "nodo_presupuesto", presupuesto)
    monkeypatch.setattr(grafo, "nodo_clima", nodo_falso("clima", llamados))
    monkeypatch.setattr(grafo, "nodo_reservas", nodo_falso("reservas", llamados))
    estado = grafo.construir_grafo().invoke(
        grafo.estado_inicial("Somos 3 con 150000. Si nos alcanza, reserva Suesca a nombre de Laura."))
    assert llamados == ["presupuesto"]  # reservas NUNCA se ejecuta
    assert any("No se creó ninguna reserva" in r for r in estado["resultados"])
    assert "No se creó ninguna reserva" in sint.mensajes[1][1]  # el sintetizador lo ve


def test_prompt_del_sintetizador_pide_datos_concretos():
    assert "probabilidad de lluvia" in grafo.PROMPT_SINTETIZADOR and "NO se creó" in grafo.PROMPT_SINTETIZADOR


def test_respuesta_final_incluye_los_datos_verificados(montar, monkeypatch):
    app, _, _ = montar(["clima", "fin"])
    monkeypatch.setattr(grafo, "MOSTRAR_DATOS_VERIFICADOS", True)
    estado = app.invoke(grafo.estado_inicial("pregunta"))
    assert estado["respuesta_final"].startswith("RESPUESTA FINAL")
    assert "Datos verificados por las herramientas:" in estado["respuesta_final"]
    assert "- [clima] listo" in estado["respuesta_final"]


def test_sin_resultados_no_hay_bloque_de_datos(montar, monkeypatch):
    app, _, _ = montar(["fin"])
    monkeypatch.setattr(grafo, "MOSTRAR_DATOS_VERIFICADOS", True)
    assert app.invoke(grafo.estado_inicial("¿Quién ganó el mundial?"))["respuesta_final"] == "RESPUESTA FINAL"
