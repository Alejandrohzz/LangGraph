"""Pruebas de datos.py y herramientas.py. No necesitan Ollama: las tools son código normal."""
import copy

import pytest

import datos
from herramientas import (calcular_saldo, consultar_disponibilidad, consultar_pronostico,
                          crear_reserva, estimar_costo, listar_destinos)


@pytest.fixture(autouse=True)
def estado_limpio():
    """Restaura cupos y reservas después de cada prueba (crear_reserva los modifica)."""
    cupos = copy.deepcopy(datos.CUPOS)
    datos.RESERVAS.clear()
    yield
    datos.CUPOS.clear()
    datos.CUPOS.update(cupos)
    datos.RESERVAS.clear()


# --- datos.py -----------------------------------------------------------------
def test_normalizar_quita_tildes_y_espacios():
    assert datos.normalizar("  Zipaquirá ") == "zipaquira"


@pytest.mark.parametrize("texto,clave", [
    ("Zipaquirá", "zipaquira"), ("zipaquira", "zipaquira"), ("la catedral", "zipaquira"),
    ("Villa de Leyva", "villa de leyva"), ("Leiva", "villa de leyva"),
    ("Guatavita", "guatavita"), ("Suesca", "suesca"), ("Chicaque", "chicaque"),
])
def test_buscar_destino(texto, clave):
    assert datos.buscar_destino(texto) == clave


def test_buscar_destino_desconocido():
    assert datos.buscar_destino("Cartagena") is None
    assert datos.buscar_destino("") is None


@pytest.mark.parametrize("texto,dia", [("sábado", "sabado"), ("Sabado", "sabado"),
                                       ("sab", "sabado"), ("Domingo", "domingo")])
def test_normalizar_dia(texto, dia):
    assert datos.normalizar_dia(texto) == dia


def test_normalizar_dia_invalido():
    assert datos.normalizar_dia("lunes") is None


def test_pesos():
    assert datos.pesos(90000) == "$90.000"
    assert datos.pesos(1250000) == "$1.250.000"


# --- Clima --------------------------------------------------------------------
def test_listar_destinos():
    r = listar_destinos.invoke({})
    assert "Laguna de Guatavita" in r and "Rocas de Suesca" in r


def test_punto_control_2_pronostico_guatavita_domingo():
    r = consultar_pronostico.invoke({"destino": "Guatavita", "dia": "domingo"})
    assert "lluvioso" in r and "80 %" in r


def test_pronostico_destino_invalido_explica_validos():
    r = consultar_pronostico.invoke({"destino": "Cartagena", "dia": "sabado"})
    assert "No conozco" in r and "Villa de Leyva" in r


def test_pronostico_dia_invalido():
    assert "sabado" in consultar_pronostico.invoke({"destino": "Suesca", "dia": "lunes"})


# --- Presupuesto --------------------------------------------------------------
def test_punto_control_2_costo_zipaquira_4_personas():
    r = estimar_costo.invoke({"destino": "Zipaquirá", "personas": 4})
    assert "$400.000" in r


def test_pregunta_3_costo_villa_de_leyva_2_personas():
    assert "$230.000" in estimar_costo.invoke({"destino": "Villa de Leyva", "personas": 2})


def test_pregunta_4_costo_suesca_3_personas():
    assert "$210.000" in estimar_costo.invoke({"destino": "Suesca", "personas": 3})


def test_costo_personas_invalidas():
    assert "mayor que cero" in estimar_costo.invoke({"destino": "Suesca", "personas": 0})


def test_pregunta_2_no_alcanza_faltan_50000():
    r = calcular_saldo.invoke({"presupuesto": 350000, "costo_total": 400000})
    assert "No alcanza" in r and "faltan $50.000" in r


def test_pregunta_4_alcanza_sobran_40000():
    r = calcular_saldo.invoke({"presupuesto": 250000, "costo_total": 210000})
    assert "Sí alcanza" in r and "sobran $40.000" in r


def test_pregunta_5_no_alcanza_faltan_60000():
    r = calcular_saldo.invoke({"presupuesto": 150000, "costo_total": 210000})
    assert "faltan $60.000" in r


def test_saldo_exacto_alcanza():
    assert "sobran $0" in calcular_saldo.invoke({"presupuesto": 100, "costo_total": 100})


# --- Reservas -----------------------------------------------------------------
def test_disponibilidad():
    assert "quedan 8 cupos" in consultar_disponibilidad.invoke({"destino": "Suesca", "dia": "sabado"})


def test_crear_reserva_descuenta_cupos_y_genera_codigo():
    r = crear_reserva.invoke({"destino": "Suesca", "dia": "sabado", "personas": 3, "responsable": "Laura"})
    assert "RES-001" in r and "Laura" in r
    assert datos.CUPOS[("suesca", "sabado")] == 5
    assert len(datos.RESERVAS) == 1


def test_codigos_consecutivos():
    crear_reserva.invoke({"destino": "Suesca", "dia": "sabado", "personas": 1, "responsable": "Laura"})
    r = crear_reserva.invoke({"destino": "Suesca", "dia": "sabado", "personas": 1, "responsable": "Ana"})
    assert "RES-002" in r


def test_reserva_sin_cupo_suficiente_no_modifica_nada():
    r = crear_reserva.invoke({"destino": "Villa de Leyva", "dia": "sabado", "personas": 5, "responsable": "Laura"})
    assert "No hay cupo suficiente" in r
    assert datos.CUPOS[("villa de leyva", "sabado")] == 2 and datos.RESERVAS == []


def test_reserva_chicaque_sabado_sin_cupos():
    r = crear_reserva.invoke({"destino": "Chicaque", "dia": "sabado", "personas": 1, "responsable": "Laura"})
    assert "No hay cupo suficiente" in r


def test_reserva_sin_responsable():
    r = crear_reserva.invoke({"destino": "Suesca", "dia": "sabado", "personas": 2, "responsable": "  "})
    assert "Falta el nombre del responsable" in r and datos.RESERVAS == []
