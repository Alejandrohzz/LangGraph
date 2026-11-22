"""
ejecutar_pruebas.py — Ejecuta las seis preguntas de prueba del taller (Parte 5).

Para cada pregunta: reinicia cupos y reservas, ejecuta el grafo, mide el tiempo, captura la traza
(supervisor + especialistas) y aplica una verificación automática contra el resultado esperado.
La verificación es una AYUDA: revisen las respuestas a mano y escriban sus observaciones en la bitácora.

Uso:
    python ejecutar_pruebas.py          -> las 6 preguntas  -> docs/resultados_pruebas.md
    python ejecutar_pruebas.py 3 4      -> solo la 3 y la 4 -> docs/resultados_pruebas_parcial.md
"""
import contextlib
import copy
import io
import re
import sys
import time
from pathlib import Path

import datos

CUPOS_INICIALES = copy.deepcopy(datos.CUPOS)


# ----------------------------------------------------------------------------
# Verificadores: devuelven lista de (descripción, cumple)
# ----------------------------------------------------------------------------
def sin_miles(texto: str) -> str:
    """'$400.000' o '400,000' -> '400000' (quita separadores de miles)."""
    return re.sub(r"(?<=\d)[.,](?=\d{3})", "", texto)


def tiene_porcentaje(texto: str, valor: int) -> bool:
    return re.search(rf"(?<!\d){valor}\s*%", texto) is not None


def verificar_1(resp, consultados, reservas):
    t = resp.lower()
    return [("llamó solo a clima", consultados == ["clima"]),
            ("dice lluvioso", "lluvi" in t),
            ("dice 80 %", tiene_porcentaje(resp, 80))]


def verificar_2(resp, consultados, reservas):
    t = sin_miles(resp)
    return [("llamó solo a presupuesto", consultados == ["presupuesto"]),
            ("costo $400.000", "400000" in t),
            ("faltan $50.000", "50000" in t)]


def verificar_3(resp, consultados, reservas):
    t = sin_miles(resp)
    return [("llamó a clima y presupuesto", sorted(consultados) == ["clima", "presupuesto"]),
            ("dice soleado", "soleado" in resp.lower()),
            ("dice 5 %", tiene_porcentaje(resp, 5)),
            ("costo $230.000", "230000" in t)]


def verificar_4(resp, consultados, reservas):
    t = sin_miles(resp)
    return [("llamó a clima, presupuesto y reservas", sorted(consultados) == ["clima", "presupuesto", "reservas"]),
            ("dice 15 %", tiene_porcentaje(resp, 15)),
            ("costo $210.000", "210000" in t),
            ("sobran $40.000", "40000" in t),
            ("creó exactamente 1 reserva", len(reservas) == 1),
            ("muestra el código RES-", "RES-" in resp)]


def verificar_5(resp, consultados, reservas):
    t = sin_miles(resp)
    return [("llamó a presupuesto", "presupuesto" in consultados),
            ("faltan $60.000", "60000" in t),
            ("NO creó ninguna reserva", len(reservas) == 0)]


def verificar_6(resp, consultados, reservas):
    return [("no llamó a ningún especialista", consultados == []),
            ("no creó reservas", len(reservas) == 0)]


PREGUNTAS = [
    (1, "¿Cómo estará el clima en Guatavita el domingo?", verificar_1),
    (2, "Somos 4 amigos con 350000 pesos. ¿Nos alcanza para ir a Zipaquirá?", verificar_2),
    (3, "Somos 2 y queremos ir a Villa de Leyva el sábado. ¿Cómo estará el clima y cuánto nos cuesta?", verificar_3),
    (4, "Somos 3 y tenemos 250000. Si no llueve mucho y nos alcanza, reserva Suesca para el sábado a nombre de Laura.", verificar_4),
    (5, "Somos 3 con 150000. Si nos alcanza, reserva Suesca el domingo a nombre de Laura.", verificar_5),
    (6, "¿Quién ganó el mundial de 2022?", verificar_6),
]


class Tee(io.TextIOBase):
    """Escribe en la consola y también guarda una copia (para la traza)."""
    def __init__(self, destino):
        self.destino, self.copia = destino, io.StringIO()

    def write(self, texto):
        self.destino.write(texto)
        self.copia.write(texto)
        return len(texto)

    def flush(self):
        self.destino.flush()


def reiniciar_datos() -> None:
    datos.CUPOS.clear()
    datos.CUPOS.update(copy.deepcopy(CUPOS_INICIALES))
    datos.RESERVAS.clear()


def ejecutar_una(numero, pregunta, verificador, app, estado_inicial) -> dict:
    reiniciar_datos()
    print(f"\n=== Pregunta {numero}: {pregunta}")
    tee = Tee(sys.stdout)
    inicio = time.perf_counter()
    error, estado = None, {}
    with contextlib.redirect_stdout(tee):
        try:
            estado = app.invoke(estado_inicial(pregunta))
        except Exception as e:  # no se oculta: queda en la bitácora
            error = f"{type(e).__name__}: {e}"
    segundos = time.perf_counter() - inicio
    respuesta = estado.get("respuesta_final", "")
    consultados = estado.get("consultados", [])
    checks = verificador(respuesta, consultados, list(datos.RESERVAS)) if not error else []
    correcta = bool(checks) and all(ok for _, ok in checks)
    print(f"Respuesta: {respuesta or error}\nTiempo: {segundos:.0f} s | Verificación automática: "
          f"{'OK' if correcta else 'REVISAR'}")
    return {"n": numero, "pregunta": pregunta, "consultados": consultados, "respuesta": respuesta,
            "error": error, "segundos": segundos, "checks": checks, "correcta": correcta,
            "traza": tee.copia.getvalue(), "reservas": list(datos.RESERVAS)}


def escribir_informe(resultados, ruta: Path) -> None:
    ruta.parent.mkdir(exist_ok=True)
    lineas = ["# Resultados de las pruebas", "",
              "Verificación automática = ayuda; las observaciones se completan a mano.", "",
              "| # | Agentes que llamó el supervisor | ¿Respuesta correcta? (auto) | Tiempo (s) | Observaciones |",
              "|---|---|---|---|---|"]
    for r in resultados:
        agentes = ", ".join(r["consultados"]) or "ninguno"
        fallos = "; ".join(d for d, ok in r["checks"] if not ok)
        obs = r["error"] or (f"Falló: {fallos}" if fallos else "")
        lineas.append(f"| {r['n']} | {agentes} | {'Sí' if r['correcta'] else 'No / revisar'} "
                      f"| {r['segundos']:.0f} | {obs} |")
    for r in resultados:
        lineas += ["", f"## Pregunta {r['n']}", f"**Pregunta:** {r['pregunta']}", "",
                   f"**Respuesta final:** {r['respuesta'] or r['error']}", "",
                   "**Verificaciones:**"]
        lineas += [f"- {'✅' if ok else '❌'} {d}" for d, ok in r["checks"]]
        lineas += ["", "**Traza:**", "```", r["traza"].strip(), "```"]
    ruta.write_text("\n".join(lineas) + "\n", encoding="utf-8")


def main(argv) -> None:
    from grafo import app, estado_inicial  # import tardío: carga los modelos

    seleccion = {int(a) for a in argv if a.isdigit()}
    elegidas = [p for p in PREGUNTAS if not seleccion or p[0] in seleccion]
    resultados = [ejecutar_una(n, q, v, app, estado_inicial) for n, q, v in elegidas]
    ruta = Path("docs") / ("resultados_pruebas_parcial.md" if seleccion else "resultados_pruebas.md")
    escribir_informe(resultados, ruta)
    print(f"\nInforme guardado en {ruta}")


if __name__ == "__main__":
    main(sys.argv[1:])
