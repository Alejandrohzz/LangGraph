"""prueba_agente.py — Prueba UN agente y muestra cada mensaje del ciclo ReAct.

Uso:
    python prueba_agente.py                  -> agente de presupuesto (pregunta del taller)
    python prueba_agente.py clima            -> agente de clima
    python prueba_agente.py reservas         -> agente de reservas
    python prueba_agente.py presupuesto "otra pregunta"
"""
import sys

import agentes

PRUEBAS = {
    "clima": (agentes.agente_clima,
              "¿Cómo estará el clima en Guatavita el domingo?"),
    "presupuesto": (agentes.agente_presupuesto,
                    "Somos 4 amigos con 350000 pesos. ¿Nos alcanza para ir a Zipaquirá?"),
    "reservas": (agentes.agente_reservas,
                 "¿Hay cupos en Suesca el sábado? Si hay, reserva 3 cupos a nombre de Laura."),
}

nombre = sys.argv[1] if len(sys.argv) > 1 else "presupuesto"
if nombre not in PRUEBAS:
    sys.exit(f"Agente desconocido '{nombre}'. Opciones: {', '.join(PRUEBAS)}")
agente, pregunta = PRUEBAS[nombre]
if len(sys.argv) > 2:
    pregunta = sys.argv[2]

print(f"Agente: {nombre}\nPregunta: {pregunta}\n")
resultado = agente.invoke({"messages": [{"role": "user", "content": pregunta}]})
for mensaje in resultado["messages"]:
    llamadas = getattr(mensaje, "tool_calls", None)  # solo los AIMessage pueden pedir tools
    print(f"--- {type(mensaje).__name__}")
    print(llamadas if llamadas else mensaje.content)
