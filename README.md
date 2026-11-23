# Planeador de fin de semana multiagente (LangGraph + Ollama)

Taller del Módulo 3 — Universidad El Bosque. Estado actual: **Partes 1 a 7** (reto elegido: confirmación humana / human-in-the-loop).

## Requisitos
- Python 3.11+
- Ollama con el modelo `qwen2.5:3b` (capacidad `tools`) en `http://localhost:11434`
  (aquí corre en el contenedor Docker `pruebachat_ollama`).

## Instalación (Windows PowerShell)
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Punto de control 1
```powershell
python prueba_ollama.py
```
Debe imprimir una frase sobre agentes de IA. La primera llamada puede tardar mientras Ollama carga el modelo.

## Variables de entorno opcionales
- `MODELO_OLLAMA` (por defecto `qwen2.5:3b`)
- `OLLAMA_URL` (por defecto `http://localhost:11434`)
- `CONFIRMAR_RESERVAS` (por defecto activo; `0` desactiva la confirmación humana del reto)

## Punto de control 2 (sin Ollama)
```powershell
python -c "from herramientas import consultar_pronostico; print(consultar_pronostico.invoke({'destino': 'Guatavita', 'dia': 'domingo'}))"
python -c "from herramientas import estimar_costo; print(estimar_costo.invoke({'destino': 'Zipaquirá', 'personas': 4}))"
pytest
```

## Punto de control 3 (requiere Ollama)
```powershell
python prueba_agente.py              # presupuesto: debe decir que faltan $50.000
python prueba_agente.py clima
python prueba_agente.py reservas
```
Se debe ver HumanMessage -> AIMessage con tool_calls -> ToolMessage -> ... -> AIMessage final.

## Punto de control 4
```powershell
pytest                      # 126 pruebas, sin Ollama (grafo con dobles de prueba)
python main.py --grafo      # imprime el grafo en Mermaid (pégalo en https://mermaid.live)
python main.py              # chat por consola (requiere Ollama)
```

## Parte 5: ejecutar las seis preguntas
```powershell
python ejecutar_pruebas.py        # las 6 preguntas -> docs/resultados_pruebas.md
python ejecutar_pruebas.py 3 4    # solo algunas   -> docs/resultados_pruebas_parcial.md
```
Reinicia cupos y reservas entre preguntas, mide tiempos y guarda la traza de cada una.

## Parte 6: API + frontend de pruebachat
```powershell
docker stop pruebachat_backend          # libera el puerto 8080 (era el backend Java)
uvicorn api:app --port 8080             # API Python, con Ollama en http://localhost:11434
docker start pruebachat_frontend        # o: docker compose -f docker/docker-compose.yml up -d --no-deps frontend
```
Abrir http://localhost:4200 (el indicador debe decir "ollama activo") y documentación en http://localhost:8080/docs.
Para volver al backend Java: detener uvicorn y `docker start pruebachat_backend`.

## Parte 7: reto — confirmación humana (human-in-the-loop)
Antes de crear una reserva, el grafo **se pausa** y pide confirmación:

```
supervisor -> confirmar_reserva (interrupt) -> sí -> reservas
                                            -> no / otra cosa -> sintetizador (sin reservar)
```
- `nodo_confirmar_reserva` usa `interrupt()` de LangGraph; el estado queda guardado en un
  **checkpointer** (`InMemorySaver`) y se reanuda con `Command(resume="sí")`.
- Ante la duda NO se reserva: solo respuestas afirmativas ("sí", "dale", "ok"...) confirman.
- **Consola:** `python main.py` muestra el resumen y pregunta `Tú:`; responde `sí` o `no`.
- **API / frontend:** el `sessionId` de la petición identifica la conversación. La primera respuesta
  trae el texto de confirmación; el siguiente mensaje del usuario ("sí"/"no") reanuda el grafo.
  Si el frontend no envía `sessionId`, todas las peticiones comparten una sesión (`sin-sesion`).
- **Pruebas automáticas (`ejecutar_pruebas.py`):** responde "sí" solo y lo deja en la traza (`[humano] ...`).
- `planear(pregunta)` sin función de confirmación responde "no": sin una persona, nunca se reserva.
- El estado en memoria se pierde al reiniciar uvicorn (para persistirlo: `SqliteSaver`/`PostgresSaver`).

## Guardias deterministas añadidas tras la Parte 5
Un modelo de 3B falla a veces; estas reglas viven en el código, no en el prompt:
- Si el usuario dio un presupuesto y el agente de presupuesto no llamó a `calcular_saldo`, el sistema
  ejecuta esa tool (la cuenta sigue siendo código, nunca el modelo).
- El supervisor no llama a `clima` si la pregunta no habla de clima, ni a `presupuesto` si no habla de
  dinero, ni a `reservas` si no se pidió reservar ni si el presupuesto no alcanza.
- Sin resultados de especialistas (p. ej. pregunta fuera de tema) la respuesta es un texto fijo.
- Los verificadores de `ejecutar_pruebas.py` ahora exigen "faltan/sobran" junto al monto.
