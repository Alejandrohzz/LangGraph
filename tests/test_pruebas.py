"""Pruebas de los verificadores de ejecutar_pruebas.py (sin Ollama)."""
import ejecutar_pruebas as ep


def ok(checks):
    return all(c for _, c in checks)


def test_sin_miles():
    assert ep.sin_miles("Costo $400.000 y 1,250,000") == "Costo $400000 y 1250000"


def test_porcentaje_no_confunde_numeros_mayores():
    assert ep.tiene_porcentaje("lluvia del 5 %", 5)
    assert not ep.tiene_porcentaje("lluvia del 15 %", 5)


def test_pregunta_1_correcta():
    assert ok(ep.verificar_1("Estará lluvioso, probabilidad de lluvia 80 %.", ["clima"], []))


def test_pregunta_2_correcta():
    assert ok(ep.verificar_2("Cuesta $400.000; faltan $50.000.", ["presupuesto"], []))


def test_pregunta_3_detecta_falta_de_porcentaje():
    checks = ep.verificar_3("Soleado. Cuesta $230.000.", ["clima", "presupuesto"], [])
    assert not ok(checks)


def test_pregunta_4_exige_una_reserva():
    resp = "15 % de lluvia, costo $210.000, sobran $40.000. Reserva RES-001."
    assert ok(ep.verificar_4(resp, ["clima", "presupuesto", "reservas"], [{"codigo": "RES-001"}]))
    assert not ok(ep.verificar_4(resp, ["clima", "presupuesto", "reservas"], []))


def test_pregunta_5_falla_si_reservo():
    resp = "Faltan $60.000."
    assert ok(ep.verificar_5(resp, ["presupuesto"], []))
    assert not ok(ep.verificar_5(resp, ["presupuesto", "reservas"], [{"codigo": "RES-001"}]))


def test_pregunta_6_sin_especialistas():
    assert ok(ep.verificar_6("Solo ayudo con salidas de fin de semana.", [], []))
    assert not ok(ep.verificar_6("...", ["clima"], []))
