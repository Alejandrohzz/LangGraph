"""
grafo.py — El sistema multiagente como un grafo de LangGraph.

              ┌──────────────┐
   START ────►│  supervisor  │◄───────────────────┐
              └──────┬───────┘                    │
        (arista condicional: ¿quién sigue?)       │
      ┌───────────┬───┴────────┬─────────────┐    │
      ▼           ▼            ▼             ▼    │
   clima     presupuesto  confirmar_reserva  sintetizador ──► END
      │           │            │  (PAUSA: interrupt)        ▲
      │           │      sí ▼  │ no ─────────────────────────┘
      │           │       reservas
      └───────────┴───────────┴────────────────────┘
              (vuelven al supervisor)

Reto Parte 7 (confirmación humana): antes de crear una reserva el grafo se pausa con interrupt() en el
nodo confirmar_reserva y se reanuda con Command(resume="sí" | "no"). Requiere un checkpointer.
"""
import operator
import re
import uuid
from typing import Annotated, Callable, Literal

from pydantic import BaseModel, Field
from typing_extensions import TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

import datos
from agentes import agente_clima, agente_presupuesto, agente_reservas, crear_modelo
from config import CONFIRMAR_RESERVAS, MAX_PASOS, MOSTRAR_DATOS_VERIFICADOS
from herramientas import calcular_saldo


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
    confirmacion: str  # "si" | "no": lo escribe el nodo confirmar_reserva (reto Parte 7)


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
- Habla SOLO de los temas que el usuario preguntó. No menciones reservas si no preguntó por ellas
  ni agregues juicios o recomendaciones que no estén en los resultados (por ejemplo, decir que
  un plan "no es factible" por el clima si no te lo preguntaron).
- Si no hay resultados, explica que puedes ayudar con clima, presupuesto y reservas
  para Guatavita, Zipaquirá, Villa de Leyva, Suesca y Chicaque."""

# Respuesta fija (sin LLM) cuando no hay ningún resultado de especialistas, p. ej. una pregunta fuera de tema.
# Es determinista: un modelo pequeño tendía a decir "todavía no hay resultados" sin aclarar el alcance.
MENSAJE_SIN_RESULTADOS = (
    "Solo puedo ayudarte a planear salidas de fin de semana cerca de Bogotá: consultar el clima, "
    "calcular costos y presupuesto, y reservar cupos en Guatavita, Zipaquirá, Villa de Leyva, Suesca "
    "y Chicaque. Con esa pregunta no puedo ayudarte; si quieres, cuéntame a qué destino quieres ir.")

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


PALABRAS_CLIMA = ("clima", "lluvi", "llueve", "llover", "temperatura", "pronostico", "soleado", "frio", "calor")
PALABRAS_DINERO = ("costo", "cuesta", "cuanto", "precio", "presupuesto", "dinero", "plata", "peso",
                   "alcanza", "gastar", "gasto")


def _menciona(pregunta: str, palabras: tuple[str, ...]) -> bool:
    t = datos.normalizar(pregunta)
    return any(p in t for p in palabras)


def _extraer_presupuesto(pregunta: str) -> int | None:
    """Primer monto en pesos de la pregunta ('350000', '$350.000', '350 mil'); None si no hay."""
    sin_miles = re.sub(r"(?<=\d)[.,](?=\d{3})", "", pregunta)
    montos = [int(n) * 1000 for n in re.findall(r"(\d+)\s*mil\b", sin_miles)]
    montos += [int(n) for n in re.findall(r"\d+", sin_miles) if int(n) >= 10000]
    return montos[0] if montos else None


def _completar_saldo(pregunta: str, datos_herramientas: list[str]) -> tuple[list[str], bool]:
    """Si el usuario dio un presupuesto y el agente NO llamó a calcular_saldo (un modelo de 3B a veces
    escribe la llamada como texto en vez de ejecutarla), el sistema ejecuta la tool él mismo.
    La cuenta sigue haciéndola calcular_saldo (código), nunca el modelo. Devuelve (datos, se_completó)."""
    presupuesto = _extraer_presupuesto(pregunta)
    union = " ".join(datos_herramientas)
    if presupuesto is None or "alcanza" in union:
        return datos_herramientas, False
    costo = re.search(r"Costo total para \d+ personas: \$([\d.]+)", union)
    if not costo:
        return datos_herramientas, False
    total = int(costo.group(1).replace(".", ""))
    saldo = calcular_saldo.invoke({"presupuesto": presupuesto, "costo_total": total})
    return datos_herramientas + [saldo], True


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
    if siguiente == "clima" and not _menciona(estado["pregunta"], PALABRAS_CLIMA):
        print("  [supervisor] el usuario no preguntó por el clima; se pasa a la respuesta final")
        siguiente = "fin"
    if siguiente == "presupuesto" and not _menciona(estado["pregunta"], PALABRAS_DINERO):
        print("  [supervisor] el usuario no preguntó por dinero; se pasa a la respuesta final")
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
        if nombre == "presupuesto":
            datos_herramientas, completado = _completar_saldo(estado["pregunta"], datos_herramientas)
            if completado:
                print("  [presupuesto] el agente no llamó a calcular_saldo; el sistema ejecutó la tool")
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
    if not estado["resultados"]:  # nadie trabajó: respuesta fija, sin gastar una llamada al modelo
        return {"respuesta_final": MENSAJE_SIN_RESULTADOS}
    respuesta = modelo_sintetizador.invoke([("system", PROMPT_SINTETIZADOR), ("human", _contexto(estado))])
    texto = respuesta.content
    verificados = [r for r in estado["resultados"] if SIN_HERRAMIENTAS not in r]
    if MOSTRAR_DATOS_VERIFICADOS and verificados:
        # Evidencia: los datos exactos que produjeron las herramientas (no el texto del modelo).
        texto += "\n\nDatos verificados por las herramientas:\n" + "\n".join(f"- {r}" for r in verificados)
    return {"respuesta_final": texto}


# ----------------------------------------------------------------------------
# 3b. RETO PARTE 7 — CONFIRMACIÓN HUMANA (human-in-the-loop)
#     interrupt() PAUSA el grafo: LangGraph guarda el estado en el checkpointer y devuelve el control a
#     quien llamó. Cuando el usuario responde, se reanuda con Command(resume=<respuesta>) y este mismo
#     nodo se vuelve a ejecutar desde el principio, pero ahora interrupt() devuelve la respuesta.
#     Por eso este nodo NO tiene efectos secundarios antes del interrupt (solo lee el estado).
# ----------------------------------------------------------------------------
AFIRMATIVAS = {"si", "s", "ok", "okay", "vale", "dale", "claro", "confirmo", "confirmar", "confirmado",
               "yes", "listo", "adelante", "correcto", "perfecto"}


def _es_afirmativo(texto) -> bool:
    """'sí', 'Si, confirmo', 'dale' -> True. Cualquier otra cosa (incluido 'no' o ruido) -> False:
    ante la duda NO se reserva."""
    palabras = re.findall(r"\w+", datos.normalizar(str(texto)))
    return bool(palabras) and palabras[0] in AFIRMATIVAS and "no" not in palabras


def _mensaje_confirmacion(estado: EstadoPlaneador) -> str:
    verificados = [r for r in estado["resultados"] if SIN_HERRAMIENTAS not in r]
    resumen = "\n".join(f"- {r}" for r in verificados) or "- (sin datos previos)"
    return ("Antes de crear la reserva necesito tu confirmación.\n\n"
            f"Tu petición: «{estado['pregunta']}»\n\n"
            f"Lo que ya se verificó:\n{resumen}\n\n"
            "¿Confirmas la reserva? Responde «sí» o «no».")


def nodo_confirmar_reserva(estado: EstadoPlaneador) -> dict:
    if not CONFIRMAR_RESERVAS:  # confirmación desactivada por configuración
        return {"confirmacion": "si"}
    respuesta = interrupt({"tipo": "confirmar_reserva", "mensaje": _mensaje_confirmacion(estado)})
    if _es_afirmativo(respuesta):
        print("  [humano] confirmó la reserva")
        return {"confirmacion": "si"}
    print(f"  [humano] no confirmó ({str(respuesta)!r}); no se reserva")
    return {"confirmacion": "no",
            "resultados": ["[sistema] El usuario no confirmó la reserva. No se creó ninguna reserva."]}


# ----------------------------------------------------------------------------
# 4. ARISTAS CONDICIONALES: leen el estado y dicen a qué nodo ir.
# ----------------------------------------------------------------------------
def enrutar(estado: EstadoPlaneador) -> str:
    return estado["siguiente"]


def enrutar_confirmacion(estado: EstadoPlaneador) -> str:
    return "reservas" if estado.get("confirmacion") == "si" else "sintetizador"


# ----------------------------------------------------------------------------
# 5. CONSTRUCCIÓN Y COMPILACIÓN DEL GRAFO
# ----------------------------------------------------------------------------
def construir_grafo(checkpointer=None):
    """checkpointer: necesario para pausar/reanudar (interrupt). Sin él, el grafo sigue funcionando
    pero la confirmación humana debe estar desactivada (CONFIRMAR_RESERVAS=0)."""
    grafo = StateGraph(EstadoPlaneador)
    grafo.add_node("supervisor", nodo_supervisor)
    grafo.add_node("clima", nodo_clima)
    grafo.add_node("presupuesto", nodo_presupuesto)
    grafo.add_node("confirmar_reserva", nodo_confirmar_reserva)
    grafo.add_node("reservas", nodo_reservas)
    grafo.add_node("sintetizador", nodo_sintetizador)

    grafo.add_edge(START, "supervisor")
    grafo.add_conditional_edges("supervisor", enrutar, {
        "clima": "clima",
        "presupuesto": "presupuesto",
        "reservas": "confirmar_reserva",  # reto Parte 7: antes de reservar, pide confirmación
        "fin": "sintetizador",
    })
    grafo.add_conditional_edges("confirmar_reserva", enrutar_confirmacion, {
        "reservas": "reservas",
        "sintetizador": "sintetizador",
    })
    for especialista in ("clima", "presupuesto", "reservas"):
        grafo.add_edge(especialista, "supervisor")
    grafo.add_edge("sintetizador", END)
    return grafo.compile(checkpointer=checkpointer)


def estado_inicial(pregunta: str) -> dict:
    return {"pregunta": pregunta, "resultados": [], "consultados": []}


# El checkpointer en memoria guarda el estado de cada conversación (thread_id) mientras el programa corre.
# Se pierde al reiniciar (para persistir se usaría SqliteSaver/PostgresSaver).
app = construir_grafo(InMemorySaver())


def _config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}


def iniciar(pregunta: str, thread_id: str) -> dict:
    """Ejecuta el grafo desde el principio. Si pide confirmación, el resultado trae '__interrupt__'."""
    return app.invoke(estado_inicial(pregunta), _config(thread_id))


def reanudar(thread_id: str, respuesta: str) -> dict:
    """Continúa un grafo pausado entregándole la respuesta del usuario."""
    return app.invoke(Command(resume=respuesta), _config(thread_id))


def _aviso(resultado: dict) -> str | None:
    """Texto de la confirmación pendiente, o None si el grafo terminó."""
    pendientes = resultado.get("__interrupt__")
    return pendientes[0].value["mensaje"] if pendientes else None


def planear(pregunta: str, confirmar: Callable[[str], str] | None = None) -> str:
    """Punto de entrada usado por main.py y ejecutar_pruebas.py.

    confirmar(mensaje) -> "sí"/"no" es quien responde a la confirmación (en main.py, input()).
    Si no se pasa, se responde "no": sin una persona que confirme, NUNCA se reserva."""
    thread_id = uuid.uuid4().hex  # una conversación nueva por pregunta (no se mezclan resultados)
    resultado = iniciar(pregunta, thread_id)
    while (aviso := _aviso(resultado)) is not None:
        resultado = reanudar(thread_id, confirmar(aviso) if confirmar else "no")
    return resultado["respuesta_final"]


# Sesiones (sessionId del frontend) con una confirmación pendiente -> thread_id del grafo pausado.
SESION_POR_DEFECTO = "sin-sesion"
_PENDIENTES: dict[str, str] = {}


def conversar(mensaje: str, sesion: str | None = None) -> str:
    """Punto de entrada de la API. Si la sesión tiene una confirmación pendiente, 'mensaje' se
    interpreta como la respuesta (sí/no) y se reanuda el grafo; si no, es una pregunta nueva.
    Si el grafo se pausa, devuelve el texto de la confirmación para mostrarlo al usuario."""
    sesion = sesion or SESION_POR_DEFECTO
    thread_id = _PENDIENTES.pop(sesion, None)
    resultado = reanudar(thread_id, mensaje) if thread_id else iniciar(mensaje, thread_id := uuid.uuid4().hex)
    aviso = _aviso(resultado)
    if aviso is not None:
        _PENDIENTES[sesion] = thread_id
        return aviso
    return resultado["respuesta_final"]
