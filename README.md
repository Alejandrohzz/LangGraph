# Planeador de fin de semana multiagente (LangGraph + Ollama)

Taller del Módulo 3 — Universidad El Bosque. Estado actual: **Parte 4 (grafo multiagente)**.

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
pytest                      # 47 pruebas, sin Ollama (grafo con dobles de prueba)
python main.py --grafo      # imprime el grafo en Mermaid (pégalo en https://mermaid.live)
python main.py              # chat por consola (requiere Ollama)
```
