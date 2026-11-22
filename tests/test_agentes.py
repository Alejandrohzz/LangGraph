"""Pruebas de agentes.py que NO necesitan Ollama (solo verifican la construcción)."""
import agentes


def test_los_tres_agentes_se_construyen():
    for agente in (agentes.agente_clima, agentes.agente_presupuesto, agentes.agente_reservas):
        assert hasattr(agente, "invoke")


def test_modelo_con_temperatura_cero():
    assert agentes.crear_modelo().temperature == 0


def test_prompts_delimitan_el_trabajo_de_cada_agente():
    assert "consultar_pronostico" in agentes.PROMPT_CLIMA
    assert "estimar_costo" in agentes.PROMPT_PRESUPUESTO and "calcular_saldo" in agentes.PROMPT_PRESUPUESTO
    assert "crear_reserva" in agentes.PROMPT_RESERVAS and "NO reserves" in agentes.PROMPT_RESERVAS
