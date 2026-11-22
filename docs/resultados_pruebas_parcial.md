# Resultados de las pruebas

Verificación automática = ayuda; las observaciones se completan a mano.

| # | Agentes que llamó el supervisor | ¿Respuesta correcta? (auto) | Tiempo (s) | Observaciones |
|---|---|---|---|---|
| 4 | clima, presupuesto, reservas | Sí | 156 |  |

## Pregunta 4
**Pregunta:** Somos 3 y tenemos 250000. Si no llueve mucho y nos alcanza, reserva Suesca para el sábado a nombre de Laura.

**Respuesta final:** Sobran $40.000. Reserva confirmada para Laura en Suesca para el sábado. Código de reserva: RES-001.

Datos verificados por las herramientas:
- [clima] Rocas de Suesca el sabado: soleado, entre 7 °C y 21 °C, probabilidad de lluvia 15 %.
- [presupuesto] Rocas de Suesca: por persona transporte $25.000 + entrada $15.000 + alimentación $30.000 = $70.000. Costo total para 3 personas: $210.000. Sí alcanza: presupuesto $250.000 - costo $210.000 = sobran $40.000.
- [reservas] Rocas de Suesca el sabado: quedan 8 cupos. Reserva confirmada RES-001: Rocas de Suesca, sabado, 3 personas, a nombre de Laura.

**Verificaciones:**
- ✅ llamó a clima, presupuesto y reservas
- ✅ dice 15 %
- ✅ costo $210.000
- ✅ sobran $40.000
- ✅ creó exactamente 1 reserva
- ✅ muestra el código RES-

**Traza:**
```
[supervisor] -> clima (Necesita saber si llueve mucho para reservar Suesca.)
  [clima] Reserva ropa ligera y cómoda para el sábado.
  [clima] datos de las herramientas: Rocas de Suesca el sabado: soleado, entre 7 °C y 21 °C, probabilidad de lluvia 15 %.
  [supervisor] -> presupuesto (El presupuesto debe ser evaluado antes de reservar)
  [presupuesto] Costo total: $210.000. Sobran $40.000.
  [presupuesto] datos de las herramientas: Rocas de Suesca: por persona transporte $25.000 + entrada $15.000 + alimentación $30.000 = $70.000. Costo total para 3 personas: $210.000. | Sí alcanza: presupuesto $250.000 - costo $210.000 = sobran $40.000.
  [supervisor] -> reservas (El usuario pidió reservar Suesca para el sábado a nombre de Laura. Los resultados de los otros agentes son suficientes para responder a esta solicitud.)
  [reservas] RES-001: Rocas de Suesca, sábado, 3 personas, a nombre de Laura.
  [reservas] datos de las herramientas: Rocas de Suesca el sabado: quedan 8 cupos. | Reserva confirmada RES-001: Rocas de Suesca, sabado, 3 personas, a nombre de Laura.
```
