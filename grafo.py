"""
grafo.py — El sistema multiagente como un grafo de LangGraph.

              ┌──────────────┐
   START ────►│  supervisor  │◄──────────────┐
              └──────┬───────┘               │
        (arista condicional: ¿quién sigue?)  │
      ┌───────────┬───┴────────┬──────────┐  │
      ▼           ▼            ▼          ▼  │
   clima     presupuesto    reservas   sintetizador ──► END
      │           │            │
      └───────────┴────────────┴───────────────┘
              (vuelven al supervisor)
"""
import operator
from typing import Annotated, Literal

from pydantic import BaseModel, Field
from typing_extensions import TypedDict

from langgraph.graph import END, START, StateGraph

import datos
from agentes import agente_clima, agente_presupuesto, agente_reservas, crear_modelo
from config import MAX_PASOS, MOSTRAR_DATOS_VERIFICADOS


# ----------------------------------------------------------------------------
# 1. ESTADO: la "memoria compartida" que viaja por todos los nodos.
#    Annotated[list, operator.add] = REDUCER: lo que devuelve un nodo se
#    AGREGA a la lista en lugar de reemplazarla.
# ----------------------------------------------------------------------------
class EstadoPlaneador(TypedDict):
    pregunta: str
    resultados: Annotated[list[str], operator.add]
    consultados: Annotated[list[str], operator.add]
    siguiente: str
    respuesta_final: str


# ----------------------------------------------------------------------------
# 2. SALIDA ESTRUCTURADA del supervisor: en vez de texto libre, el modelo
#    debe devolver un objeto con estos campos (Ollama lo garantiza con un
#    JSON Schema). Así la decisión de enrutamiento es confiable.
# ----------------------------------------------------------------------------
class Decision(BaseModel):
    siguiente: Literal["clima", "presupuesto", "reservas", "fin"] = Field(
        description="Agente que debe trabajar ahora, o 'fin' si ya se puede responder.")
    motivo: str = Field(description="Explicación breve de la decisión.")


SIN_HERRAMIENTAS = "(sin datos de herramientas)"

PROMPT_SUPERVISOR = """Eres el SUPERVISOR de un planeador de salidas de fin de semana cerca de Bogotá.
Coordinas a tres agentes especialistas:
- clima: pronóstico del tiempo de un destino para el sábado o el domingo.
- presupuesto: costo del plan para un grupo y si el dinero alcanza.
- reservas: cupos disponibles y creación de reservas.
Lee la pregunta del usuario y los resultados que ya existen, y decide quién trabaja ahora.
Reglas:
1. Elige solo agentes que la pregunta realmente necesita y que no hayan sido consultados.
2. Si el usuario quiere reservar con una condición (clima, dinero), consulta primero esos agentes
   y deja "reservas" de último.
3. Cada tema de la pregunta necesita su agente: clima, lluvia o temperatura -> clima;
   cuánto cuesta, dinero o presupuesto, si alcanza -> presupuesto.
   Elige "reservas" SOLO si el usuario pide reservar explícitamente (reserva, reservar, aparta).
   Si solo pregunta por clima o costo, NUNCA elijas "reservas".
   No respondas "fin" mientras quede un tema de la pregunta sin cubrir.
4. Si ya hay información suficiente, o la pregunta no trata de estos temas, responde "fin"."""

PROMPT_SINTETIZADOR = """Eres el asistente final de un planeador de salidas de fin de semana.
Redacta la respuesta para el usuario usando SOLO los resultados de los agentes.
- No inventes datos que no estén en los resultados.
- Organiza la respuesta en un párrafo corto o en viñetas, en español y con tono amable.
- Incluye siempre los datos concretos de los resultados: probabilidad de lluvia en %, costo total,
  cuánto sobra o falta, cupos y código de reserva.
- Si se hizo una reserva, muestra el código. Si un resultado dice que NO se creó una reserva,
  dilo claramente y explica el motivo.
- Si no hay resultados, explica que puedes ayudar con clima, presupuesto y reservas
  para Guatavita, Zipaquirá, Villa de Leyva, Suesca y Chicaque."""

modelo_supervisor = crear_modelo().with_structured_output(Decision)
modelo_sintetizador = crear_modelo()


def _contexto(estado: EstadoPlaneador) -> str:
    """Texto con la pregunta y lo que ya respondieron los agentes."""
    previos = "\n".join(estado["resultados"]) or "(todavía no hay resultados)"
    return f"Pregunta del usuario: {estado['pregunta']}\n\nResultados de otros agentes:\n{previos}"


# ----------------------------------------------------------------------------
# 3. NODOS: funciones que reciben el estado y devuelven SOLO lo que cambian.
# ----------------------------------------------------------------------------
# Palabras que indican que la pregunta trata de clima, dinero, reservas o de planear una salida.
# Es un filtro de entrada barato y determinista: si no aparece ninguna (ni un destino), la pregunta
# está fuera de tema y ni siquiera se consulta al modelo supervisor.
PALABRAS_DOMINIO = (
    "clima", "lluvi", "llueve", "temperatura", "pronostico", "soleado", "frio", "calor",
    "costo", "cuesta", "cuanto", "precio", "presupuesto", "dinero", "plata", "peso", "alcanza", "gastar",
    "reserv", "cupo", "disponib", "aparta",
    "plan", "viaj", "salida", "paseo", "excursion", "destino", "fin de semana", "sabado", "domingo",
)


def _es_del_dominio(pregunta: str) -> bool:
    t = datos.normalizar(pregunta)
    return datos.buscar_destino(pregunta) is not None or any(p in t for p in PALABRAS_DOMINIO)


def _pide_reservar(pregunta: str) -> bool:
    """True si el usuario habló de reservar. Crear una reserva tiene efectos, así que el sistema
    no depende solo del modelo: sin una petición explícita no se llama al agente de reservas."""
    return "reserv" in datos.normalizar(pregunta)


def _presupuesto_no_alcanza(estado: EstadoPlaneador) -> bool:
    """True si calcular_saldo (vía el agente de presupuesto) dijo que el dinero no alcanza."""
    return any(r.startswith("[presupuesto]") and "No alcanza" in r for r in estado["resultados"])


def nodo_supervisor(estado: EstadoPlaneador) -> dict:
    consultados = estado["consultados"]
    if len(consultados) >= MAX_PASOS:  # límite de autonomía
        return {"siguiente": "fin"}
    if not consultados and not _es_del_dominio(estado["pregunta"]):
        print("  [supervisor] pregunta fuera de tema; se responde sin consultar especialistas")
        return {"siguiente": "fin"}
    pendientes = [a for a in ("clima", "presupuesto", "reservas") if a not in consultados]
    mensaje = (_contexto(estado) +
               f"\n\nAgentes ya consultados: {', '.join(consultados) or 'ninguno'}" +
               f"\nAgentes que todavía puedes elegir: {', '.join(pendientes) or 'ninguno'} (o 'fin')")
    try:
        decision = modelo_supervisor.invoke([("system", PROMPT_SUPERVISOR), ("human", mensaje)])
        siguiente = decision.siguiente
        print(f"  [supervisor] -> {siguiente} ({decision.motivo})")
    except Exception as error:  # el modelo no devolvió un JSON válido
        print(f"  [supervisor] decisión inválida ({error}); se pasa a la respuesta final")
        siguiente = "fin"
    if siguiente in consultados:  # evita ciclos infinitos
        siguiente = "fin"
    if siguiente == "reservas" and not _pide_reservar(estado["pregunta"]):
        print("  [supervisor] el usuario no pidió reservar; se pasa a la respuesta final")
        siguiente = "fin"
    if siguiente == "reservas" and _presupuesto_no_alcanza(estado):
        # Guardia determinista: nunca se reserva si el presupuesto no alcanza, decida lo que decida el modelo.
        print("  [supervisor] el presupuesto no alcanza; NO se llama al agente de reservas")
        return {"siguiente": "fin",
                "resultados": ["[sistema] No se creó ninguna reserva porque el presupuesto no alcanza."]}
    return {"siguiente": siguiente}


def crear_nodo_especialista(nombre: str, agente):
    """Fábrica de nodos: envuelve un agente (create_agent) como nodo del grafo.

    Lo que se guarda en el estado son, siempre que existan, los resultados de las HERRAMIENTAS
    (ToolMessage): son datos producidos por código. El texto que redacta un modelo pequeño puede
    parafrasear mal o inventar (por ejemplo cambiar "5 %" por "poca lluvia"). Si el agente no usó
    ninguna herramienta, se guarda su texto."""
    def nodo(estado: EstadoPlaneador) -> dict:
        resultado = agente.invoke({"messages": [{"role": "user", "content": _contexto(estado)}]})
        mensajes = resultado["messages"]
        texto = mensajes[-1].content
        datos_herramientas = [m.content for m in mensajes
                              if getattr(m, "type", "") == "tool"
                              and getattr(m, "status", "success") != "error"]
        if nombre == "reservas" and not any(d.startswith("Reserva confirmada") for d in datos_herramientas):
            datos_herramientas.append("No se creó ninguna reserva.")
        print(f"  [{nombre}] {texto}")
        if datos_herramientas:
            print(f"  [{nombre}] datos de las herramientas: {' | '.join(datos_herramientas)}")
        guardado = " ".join(datos_herramientas) if datos_herramientas else f"{SIN_HERRAMIENTAS} {texto}"
        return {"resultados": [f"[{nombre}] {guardado}"], "consultados": [nombre]}
    return nodo


nodo_clima = crear_nodo_especialista("clima", agente_clima)
nodo_presupuesto = crear_nodo_especialista("presupuesto", agente_presupuesto)
nodo_reservas = crear_nodo_especialista("reservas", agente_reservas)


def nodo_sintetizador(estado: EstadoPlaneador) -> dict:
    respuesta = modelo_sintetizador.invoke([("system", PROMPT_SINTETIZADOR), ("human", _contexto(estado))])
    texto = respuesta.content
    verificados = [r for r in estado["resultados"] if SIN_HERRAMIENTAS not in r]
    if MOSTRAR_DATOS_VERIFICADOS and verificados:
        # Evidencia: los datos exactos que produjeron las herramientas (no el texto del modelo).
        texto += "\n\nDatos verificados por las herramientas:\n" + "\n".join(f"- {r}" for r in verificados)
    return {"respuesta_final": texto}


# ----------------------------------------------------------------------------
# 4. ARISTA CONDICIONAL: lee el estado y dice a qué nodo ir.
# ----------------------------------------------------------------------------
def enrutar(estado: EstadoPlaneador) -> str:
    return estado["siguiente"]


# ----------------------------------------------------------------------------
# 5. CONSTRUCCIÓN Y COMPILACIÓN DEL GRAFO
# ----------------------------------------------------------------------------
def construir_grafo():
    grafo = StateGraph(EstadoPlaneador)
    grafo.add_node("supervisor", nodo_supervisor)
    grafo.add_node("clima", nodo_clima)
    grafo.add_node("presupuesto", nodo_presupuesto)
    grafo.add_node("reservas", nodo_reservas)
    grafo.add_node("sintetizador", nodo_sintetizador)

    grafo.add_edge(START, "supervisor")
    grafo.add_conditional_edges("supervisor", enrutar, {
        "clima": "clima",
        "presupuesto": "presupuesto",
        "reservas": "reservas",
        "fin": "sintetizador",
    })
    for especialista in ("clima", "presupuesto", "reservas"):
        grafo.add_edge(especialista, "supervisor")
    grafo.add_edge("sintetizador", END)
    return grafo.compile()


def estado_inicial(pregunta: str) -> dict:
    return {"pregunta": pregunta, "resultados": [], "consultados": []}


app = construir_grafo()


def planear(pregunta: str) -> str:
    """Punto de entrada usado por main.py y api.py."""
    estado_final = app.invoke(estado_inicial(pregunta))
    return estado_final["respuesta_final"]
