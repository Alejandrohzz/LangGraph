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


def test_informe_se_guarda_aunque_se_interrumpa(tmp_path):
    class AppFalsa:
        def __init__(self):
            self.n = 0

        def invoke(self, _estado, _config=None):
            self.n += 1
            if self.n == 2:
                raise KeyboardInterrupt
            return {"respuesta_final": "Estará lluvioso, lluvia 80 %.", "consultados": ["clima"]}

    ruta = tmp_path / "docs" / "informe.md"
    elegidas = [p for p in ep.PREGUNTAS if p[0] in (1, 2)]
    resultados = ep.ejecutar_todas(elegidas, AppFalsa(), lambda q: {}, ruta)
    assert len(resultados) == 1 and ruta.exists()
    assert "Pregunta 1" in ruta.read_text(encoding="utf-8")


def test_pregunta_2_no_se_deja_enganar_por_la_entrada_de_50000():
    # Falso positivo detectado en la Parte 5: "$50.000" aparece como entrada, pero no dice "faltan".
    resp = "Costo total $400.000 (entrada $50.000). No alcanza."
    assert not ok(ep.verificar_2(resp, ["presupuesto"], []))


def test_pregunta_4_y_5_exigen_sobran_y_faltan_con_su_monto():
    r4 = "15 % de lluvia. Costo $210.000. Reserva RES-001."
    assert not ok(ep.verificar_4(r4, ["clima", "presupuesto", "reservas"], [{"codigo": "RES-001"}]))
    assert not ok(ep.verificar_5("Cuesta $210.000 y tienen $150.000.", ["presupuesto"], []))


def test_pregunta_6_exige_explicar_el_alcance():
    assert not ok(ep.verificar_6("No hay resultados.", [], []))


def test_invocar_con_confirmacion_responde_si_automaticamente():
    from langgraph.types import Command

    class Interrupcion:
        value = {"mensaje": "¿Confirmas?"}

    class AppPausada:
        def __init__(self):
            self.entradas = []

        def invoke(self, entrada, config=None):
            self.entradas.append(entrada)
            if not isinstance(entrada, Command):
                return {"__interrupt__": [Interrupcion()]}
            return {"respuesta_final": "ok", "consultados": ["reservas"]}

    app = AppPausada()
    estado = ep.invocar_con_confirmacion(app, lambda q: {"pregunta": q}, "reserva Suesca")
    assert estado["respuesta_final"] == "ok" and app.entradas[1].resume == "sí"
