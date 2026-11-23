"""Pruebas del grafo SIN Ollama: se reemplazan el supervisor, los especialistas y el sintetizador
por dobles de prueba para verificar el enrutamiento, los reducers y los límites de autonomía."""
import pytest

import grafo
from ejecutar_pruebas import PREGUNTAS
from grafo import Decision


CLIMA = "¿Cómo estará el clima?"
CLIMA_Y_COSTO = "¿Cómo estará el clima y cuánto cuesta?"
PREGUNTA_4 = PREGUNTAS[3][1]


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
    def _montar(decisiones, confirmar=False, checkpointer=None):
        llamados = []
        sint = SintetizadorFalso()
        monkeypatch.setattr(grafo, "MOSTRAR_DATOS_VERIFICADOS", False)
        monkeypatch.setattr(grafo, "CONFIRMAR_RESERVAS", confirmar)
        monkeypatch.setattr(grafo, "modelo_supervisor", SupervisorFalso(decisiones))
        monkeypatch.setattr(grafo, "modelo_sintetizador", sint)
        for n in ("clima", "presupuesto", "reservas"):
            monkeypatch.setattr(grafo, f"nodo_{n}", nodo_falso(n, llamados))
        return grafo.construir_grafo(checkpointer), llamados, sint
    return _montar


def test_pregunta_3_clima_y_presupuesto(montar):
    app, llamados, _ = montar(["clima", "presupuesto", "fin"])
    estado = app.invoke(grafo.estado_inicial(CLIMA_Y_COSTO))
    assert llamados == ["clima", "presupuesto"]
    assert estado["consultados"] == ["clima", "presupuesto"]          # el reducer acumula
    assert len(estado["resultados"]) == 2
    assert estado["respuesta_final"] == "RESPUESTA FINAL"


def test_pregunta_4_tres_especialistas_y_limite_de_autonomia(montar):
    # El supervisor "quisiera" seguir, pero tras 3 especialistas se corta sin preguntarle.
    app, llamados, _ = montar(["clima", "presupuesto", "reservas"])
    estado = app.invoke(grafo.estado_inicial(PREGUNTA_4))
    assert llamados == ["clima", "presupuesto", "reservas"]
    assert estado["respuesta_final"] == "RESPUESTA FINAL"


def test_limite_configurable(montar, monkeypatch):
    monkeypatch.setattr(grafo, "MAX_PASOS", 1)
    app, llamados, _ = montar(["clima", "presupuesto"])
    app.invoke(grafo.estado_inicial(CLIMA))
    assert llamados == ["clima"]


def test_pregunta_6_fuera_de_tema_no_llama_especialistas(montar):
    app, llamados, sint = montar(["fin"])
    estado = app.invoke(grafo.estado_inicial("¿Quién ganó el mundial de 2022?"))
    assert llamados == []
    assert estado["respuesta_final"] == grafo.MENSAJE_SIN_RESULTADOS
    assert sint.mensajes is None  # la respuesta fija no gasta una llamada al modelo
    assert "fin de semana" in estado["respuesta_final"]


def test_no_repite_especialistas(montar):
    app, llamados, _ = montar(["clima", "clima"])
    estado = app.invoke(grafo.estado_inicial(CLIMA))
    assert llamados == ["clima"]
    assert estado["consultados"] == ["clima"]


def test_decision_invalida_finaliza_de_forma_segura(montar):
    app, llamados, _ = montar([ValueError("JSON inválido")])
    estado = app.invoke(grafo.estado_inicial(CLIMA))
    assert llamados == []
    assert estado["respuesta_final"] == grafo.MENSAJE_SIN_RESULTADOS


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
    assert salida == {"resultados": [f"[clima] {grafo.SIN_HERRAMIENTAS} respuesta del agente"],
                      "consultados": ["clima"]}


def test_mermaid_contiene_los_seis_nodos():
    texto = grafo.app.get_graph().draw_mermaid()
    for nodo in ("supervisor", "clima", "presupuesto", "confirmar_reserva", "reservas", "sintetizador"):
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
    app.invoke(grafo.estado_inicial(CLIMA))
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
    estado = app.invoke(grafo.estado_inicial(CLIMA))
    assert estado["respuesta_final"].startswith("RESPUESTA FINAL")
    assert "Datos verificados por las herramientas:" in estado["respuesta_final"]
    assert "- [clima] listo" in estado["respuesta_final"]


def test_sin_resultados_no_hay_bloque_de_datos(montar, monkeypatch):
    app, _, _ = montar(["fin"])
    monkeypatch.setattr(grafo, "MOSTRAR_DATOS_VERIFICADOS", True)
    assert app.invoke(grafo.estado_inicial("¿Quién ganó el mundial?"))["respuesta_final"] == grafo.MENSAJE_SIN_RESULTADOS


@pytest.mark.parametrize("numero,pregunta,_v", PREGUNTAS)
def test_filtro_de_dominio_con_las_seis_preguntas(numero, pregunta, _v):
    assert grafo._es_del_dominio(pregunta) == (numero != 6)


def test_pregunta_fuera_de_tema_ni_siquiera_consulta_al_supervisor(montar):
    app, llamados, _ = montar([])  # si se llamara al supervisor, fallaría (lista vacía)
    estado = app.invoke(grafo.estado_inicial("¿Quién ganó el mundial de 2022?"))
    assert llamados == [] and grafo.modelo_supervisor.llamadas == 0
    assert estado["respuesta_final"] == grafo.MENSAJE_SIN_RESULTADOS


def test_el_bloque_de_datos_excluye_lo_que_no_vino_de_herramientas(monkeypatch):
    monkeypatch.setattr(grafo, "modelo_sintetizador", SintetizadorFalso())
    estado = grafo.estado_inicial("x")
    estado["resultados"] = [f"[clima] {grafo.SIN_HERRAMIENTAS} puro texto del modelo",
                            "[presupuesto] Costo total: $230.000."]
    texto = grafo.nodo_sintetizador(estado)["respuesta_final"]
    assert "- [presupuesto] Costo total: $230.000." in texto
    assert "puro texto del modelo" not in texto


# ----------------------------------------------------------------------------
# Correcciones de la Parte 5
# ----------------------------------------------------------------------------
def test_extraer_presupuesto():
    assert grafo._extraer_presupuesto("Somos 4 amigos con 350000 pesos") == 350000
    assert grafo._extraer_presupuesto("tenemos $250.000") == 250000
    assert grafo._extraer_presupuesto("tenemos 300 mil") == 300000
    assert grafo._extraer_presupuesto("Somos 3, ¿cuánto cuesta Suesca?") is None


def test_si_el_agente_no_llamo_calcular_saldo_el_sistema_ejecuta_la_tool():
    costo = ("Catedral de Sal de Zipaquirá: por persona ... = $100.000. "
             "Costo total para 4 personas: $400.000.")
    datos_, completado = grafo._completar_saldo("Somos 4 con 350000. ¿Nos alcanza?", [costo])
    assert completado and "faltan $50.000" in datos_[-1]


def test_no_completa_saldo_si_ya_existe_o_no_hay_presupuesto():
    costo = "Costo total para 4 personas: $400.000."
    ya = [costo, "No alcanza: presupuesto $350.000 - costo $400.000 = faltan $50.000."]
    assert grafo._completar_saldo("con 350000", ya) == (ya, False)
    assert grafo._completar_saldo("¿cuánto cuesta para 4?", [costo]) == ([costo], False)


def test_nodo_presupuesto_completa_el_saldo_cuando_el_agente_lo_omite():
    from langchain_core.messages import AIMessage, ToolMessage

    class AgenteQueOlvidaElSaldo:
        def invoke(self, _entrada):
            return {"messages": [
                ToolMessage(content="Zipaquirá ... Costo total para 4 personas: $400.000.", tool_call_id="1"),
                AIMessage(content="Hazlo tú mismo: calcular_saldo(presupuesto=350000, costo_total=400000)")]}

    salida = grafo.crear_nodo_especialista("presupuesto", AgenteQueOlvidaElSaldo())(
        grafo.estado_inicial("Somos 4 amigos con 350000 pesos. ¿Nos alcanza para ir a Zipaquirá?"))
    assert "faltan $50.000" in salida["resultados"][0]
    assert "Hazlo tú mismo" not in salida["resultados"][0]


def test_no_llama_a_clima_si_no_preguntaron_por_clima(montar):
    # Pregunta 5: el supervisor "quisiera" clima, pero el usuario solo habló de dinero y reserva.
    app, llamados, _ = montar(["presupuesto", "clima", "fin"])
    app.invoke(grafo.estado_inicial(PREGUNTAS[4][1]))
    assert llamados == ["presupuesto"]


def test_no_llama_a_presupuesto_si_no_preguntaron_por_dinero(montar):
    app, llamados, _ = montar(["presupuesto"])
    app.invoke(grafo.estado_inicial("¿Cómo estará el clima en Suesca el sábado?"))
    assert llamados == []


@pytest.mark.parametrize("numero,pregunta,_v", PREGUNTAS)
def test_las_seis_preguntas_siguen_pudiendo_llamar_a_sus_agentes(numero, pregunta, _v):
    esperados = {1: {"clima"}, 2: {"presupuesto"}, 3: {"clima", "presupuesto"},
                 4: {"clima", "presupuesto", "reservas"}, 5: {"presupuesto"}, 6: set()}[numero]
    permitidos = set()
    if grafo._menciona(pregunta, grafo.PALABRAS_CLIMA):
        permitidos.add("clima")
    if grafo._menciona(pregunta, grafo.PALABRAS_DINERO):
        permitidos.add("presupuesto")
    if grafo._pide_reservar(pregunta):
        permitidos.add("reservas")
    assert esperados <= permitidos  # ningún guardia bloquea a un agente que la pregunta necesita


# ----------------------------------------------------------------------------
# RETO PARTE 7: confirmación humana (interrupt + checkpointer)
# ----------------------------------------------------------------------------
from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402
from langgraph.types import Command  # noqa: E402


def _config(hilo):
    return {"configurable": {"thread_id": hilo}}


def test_la_reserva_se_pausa_y_no_se_ejecuta_hasta_confirmar(montar):
    app, llamados, _ = montar(["clima", "presupuesto", "reservas"], confirmar=True, checkpointer=InMemorySaver())
    pausado = app.invoke(grafo.estado_inicial(PREGUNTA_4), _config("t1"))
    assert "__interrupt__" in pausado
    assert "reservas" not in llamados                      # NADA se reservó todavía
    assert "¿Confirmas la reserva?" in pausado["__interrupt__"][0].value["mensaje"]
    assert app.get_state(_config("t1")).next == ("confirmar_reserva",)


def test_confirmar_con_si_ejecuta_la_reserva(montar):
    app, llamados, _ = montar(["clima", "presupuesto", "reservas"], confirmar=True, checkpointer=InMemorySaver())
    app.invoke(grafo.estado_inicial(PREGUNTA_4), _config("t2"))
    final = app.invoke(Command(resume="sí"), _config("t2"))
    assert llamados == ["clima", "presupuesto", "reservas"]
    assert final["respuesta_final"] == "RESPUESTA FINAL" and "__interrupt__" not in final


@pytest.mark.parametrize("respuesta", ["no", "No, gracias", "quizás", "", "cuánto cuesta Suesca"])
def test_cualquier_respuesta_que_no_sea_si_cancela(montar, respuesta):
    app, llamados, sint = montar(["clima", "presupuesto", "reservas"], confirmar=True, checkpointer=InMemorySaver())
    app.invoke(grafo.estado_inicial(PREGUNTA_4), _config("t3"))
    final = app.invoke(Command(resume=respuesta), _config("t3"))
    assert "reservas" not in llamados                      # no se creó la reserva
    assert "No se creó ninguna reserva" in sint.mensajes[1][1]   # el sintetizador lo sabe
    assert final["confirmacion"] == "no"


def test_la_pausa_conserva_el_estado_acumulado(montar):
    app, _, sint = montar(["clima", "presupuesto", "reservas"], confirmar=True, checkpointer=InMemorySaver())
    app.invoke(grafo.estado_inicial(PREGUNTA_4), _config("t4"))
    app.invoke(Command(resume="si"), _config("t4"))
    assert "[clima] listo" in sint.mensajes[1][1] and "[presupuesto] listo" in sint.mensajes[1][1]


def test_dos_conversaciones_no_se_mezclan(montar):
    app, llamados, _ = montar(["clima", "presupuesto", "reservas", "clima", "presupuesto", "reservas"],
                              confirmar=True, checkpointer=InMemorySaver())
    app.invoke(grafo.estado_inicial(PREGUNTA_4), _config("A"))
    app.invoke(grafo.estado_inicial(PREGUNTA_4), _config("B"))
    assert app.get_state(_config("A")).next == ("confirmar_reserva",)
    app.invoke(Command(resume="no"), _config("A"))
    assert app.get_state(_config("B")).next == ("confirmar_reserva",)   # B sigue pausada


def test_sin_confirmacion_configurada_no_se_pausa(montar):
    app, llamados, _ = montar(["clima", "presupuesto", "reservas"], confirmar=False)
    estado = app.invoke(grafo.estado_inicial(PREGUNTA_4))
    assert llamados == ["clima", "presupuesto", "reservas"] and "__interrupt__" not in estado


def test_no_se_pide_confirmacion_si_no_hay_reserva(montar):
    app, llamados, _ = montar(["clima", "fin"], confirmar=True, checkpointer=InMemorySaver())
    estado = app.invoke(grafo.estado_inicial(CLIMA), _config("t5"))
    assert "__interrupt__" not in estado and llamados == ["clima"]


@pytest.mark.parametrize("texto,esperado", [
    ("sí", True), ("Si", True), ("SÍ, confirmo", True), ("dale", True), ("ok", True),
    ("no", False), ("si no", False), ("No, mejor no", False), ("", False), ("tal vez", False), (None, False)])
def test_es_afirmativo(texto, esperado):
    assert grafo._es_afirmativo(texto) is esperado


def test_planear_sin_quien_confirme_nunca_reserva(montar, monkeypatch):
    app, llamados, _ = montar(["clima", "presupuesto", "reservas"], confirmar=True, checkpointer=InMemorySaver())
    monkeypatch.setattr(grafo, "app", app)
    respuesta = grafo.planear(PREGUNTA_4)           # sin callback -> responde "no"
    assert respuesta == "RESPUESTA FINAL" and "reservas" not in llamados


def test_planear_con_callback_que_confirma(montar, monkeypatch):
    app, llamados, _ = montar(["clima", "presupuesto", "reservas"], confirmar=True, checkpointer=InMemorySaver())
    monkeypatch.setattr(grafo, "app", app)
    avisos = []
    grafo.planear(PREGUNTA_4, confirmar=lambda aviso: avisos.append(aviso) or "sí")
    assert len(avisos) == 1 and "Suesca" in avisos[0] and llamados[-1] == "reservas"


def test_conversar_pide_confirmacion_y_la_reanuda_con_el_siguiente_mensaje(montar, monkeypatch):
    app, llamados, _ = montar(["clima", "presupuesto", "reservas"], confirmar=True, checkpointer=InMemorySaver())
    monkeypatch.setattr(grafo, "app", app)
    grafo._PENDIENTES.clear()
    aviso = grafo.conversar(PREGUNTA_4, "sesion-1")
    assert "¿Confirmas la reserva?" in aviso and "reservas" not in llamados
    assert "sesion-1" in grafo._PENDIENTES
    final = grafo.conversar("sí", "sesion-1")
    assert final == "RESPUESTA FINAL" and llamados[-1] == "reservas"
    assert "sesion-1" not in grafo._PENDIENTES


def test_conversar_las_sesiones_son_independientes(montar, monkeypatch):
    app, llamados, _ = montar(["clima", "presupuesto", "reservas"] * 2, confirmar=True, checkpointer=InMemorySaver())
    monkeypatch.setattr(grafo, "app", app)
    grafo._PENDIENTES.clear()
    grafo.conversar(PREGUNTA_4, "ana")
    grafo.conversar(PREGUNTA_4, "luis")
    grafo.conversar("no", "ana")                     # ana cancela
    assert "luis" in grafo._PENDIENTES and "ana" not in grafo._PENDIENTES
    assert "reservas" not in llamados                # nadie reservó
