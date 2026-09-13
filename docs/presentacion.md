# Motor forense · Resumen para la presentación (~3 min)

> Versión corta de [`como_funciona.md`](como_funciona.md). Solo lo que hay que decir en el
> pitch. Los detalles técnicos quedan para las preguntas.

---

## 1. En resumen

1. Recibe los **8 archivos CSV** de la contabilidad de una empresa (proveedores, facturas,
   libro mayor, banco, órdenes de compra, contratos, empleados y lista EFOS del SAT).
2. Corre **24 reglas escritas en SQL**: 20 detectan los 5 tipos de fraude del reto y 4 revisan
   la **calidad de los datos**.
3. Cada regla produce **señales** (indicios que apuntan a un registro exacto). Una señal
   **no es una acusación**.
4. Un **ensamblador** junta las señales por esquema y decide: **acusa** solo si la evidencia
   es independiente, suficiente y tiene monto en pesos; si no, **descarta la pista y explica
   por qué**.
5. Entrega un `submission.json` que pasa el validador oficial y un **case file** legible con
   el rastro del dinero.

---

## 2. Principios de diseño

| Principio | Qué significa | Por qué importa |
|---|---|---|
| **Determinista** | Mismos datos + mismo seed ⇒ mismos hallazgos, montos y razones. | Los jueces pueden repetir la corrida; un auditor puede reproducir el caso. |
| **Sin LLM en la detección** | Reglas SQL, umbrales fijos y narrativas por plantilla. 0 llamadas a LLM, $0 MXN. | Nada se inventa: cada frase sale de un dato calculado. |
| **LLM solo en el chatbot** *(planeado)* | Responde preguntas sobre un reporte ya generado; no cambia hallazgos ni montos. | Se conversa con el reporte sin romper el determinismo. |
| **Offline** | Corre en memoria (DuckDB), sin red. | El case file se regenera sin conexión. |
| **Probar antes de acusar** | ≥2 evidencias independientes (o una regla contundente), ≥3 registros citados y monto que cuadre. | Acusar a un proveedor honesto pesa tanto como no encontrar el fraude. |
| **Trazable** | Cada señal y cada prueba apunta a **una fila concreta**. | Cualquier número del reporte se verifica abriendo la fila. |
| **Respuestas aisladas** | El motor nunca ve las respuestas correctas de la evaluación. | No hay trampa posible, y se puede comprobar. |

---

## 3. El flujo en una línea

```text
8 CSV → 24 reglas SQL → señales → ensamblador (¿acuso o descarto?) → validador oficial → case file
```

---

## 4. Qué detecta: los 5 fraudes

| Fraude | En palabras simples | Ejemplo de señal |
|---|---|---|
| **Proveedor fantasma** | Factura trabajo que nunca se hizo. | Está en la lista EFOS del SAT; varios proveedores cobran en la misma cuenta. |
| **Moche (kickback)** | El dinero regresa a un empleado. | Un pago llega a la cuenta bancaria de un empleado. |
| **Round tripping** | El dinero sale y vuelve en círculo. | A paga a B y B le devuelve casi lo mismo días después. |
| **Fraccionamiento** | Partir una compra para evadir el límite de aprobación. | Varias órdenes seguidas, mismo aprobador, que juntas superan $50,000. |
| **Inflado de ingresos** | Ventas que no existieron. | Factura cancelada que sigue registrada como ingreso. |

Además, 4 reglas de **calidad de datos** (pólizas descuadradas, RFC o CLABE mal capturados)
que se reportan aparte y **nunca acusan**.

---

## 5. Lo que nos diferencia: cómo decide acusar

Una señal sola no basta. Para acusar se necesita **todo** esto:

1. **Dos evidencias de naturaleza distinta.** Dos reglas que miran el mismo hecho no cuentan
   doble. Solo dos casos bastan solos: proveedor confirmado por el SAT y pago a la cuenta de
   un empleado.
2. **Al menos 3 registros citados** que prueben la participación de cada acusado.
3. **Un monto en pesos** que cuadre con los registros (tolerancia 2%).
4. **Pasar el validador oficial.** Si no pasa, no se publica nada.

Si falta algo, la pista **se cierra con una razón concreta** (qué se revisó y qué faltó).

**Ejemplo de proveedor honesto (decoy):** es nuevo y está "en investigación" en el SAT. Son dos
señales, pero tiene órdenes de compra y contrato con la empresa, así que **no se acusa** y se
explica por qué.

Cada acusación sale con nivel de confianza: **proven** (un registro prueba el hecho por sí solo)
o **probable** (varias señales independientes apuntan a lo mismo).

---

## 6. Qué entrega

- **Case file** para un auditor no técnico:
  - resumen ejecutivo con número de hallazgos y **exposición total en pesos**;
  - por hallazgo: norma violada (p. ej. Art. 69-B CFF), monto, confianza, **diagrama del rastro
    del dinero** y tabla de pruebas;
  - **pistas descartadas con su razón**, en el cuerpo del reporte;
  - costo de la corrida: 0 llamadas a LLM, $0 MXN y segundos de ejecución.
- **Bitácora** de cada decisión, para responder "¿por qué?" sin volver a correr nada.

---

## 7. Cómo lo medimos

- Generador de empresas sintéticas con **fraudes plantados y decoys**.
- Calibramos con unos seeds y reportamos sobre **6 casos reservados** que nunca se usaron para
  ajustar.
- Medimos **recall** (fraudes encontrados) **y tasa de falsas acusaciones** (decoys acusados).
- **[Agregar aquí la fila TOTAL de la tabla de resultados.]**

---

## Guion sugerido (3 min)

| Tiempo | Qué decir | Sección |
|---|---|---|
| 0:00–0:20 | El problema: el fraude está escondido en los libros y acusar a un honesto cuesta caro. | — |
| 0:20–0:50 | Qué hace el sistema y sus principios: determinista, sin LLM, trazable. | 1, 2 |
| 0:50–1:20 | Los 5 fraudes y cómo las reglas generan señales. | 3, 4 |
| 1:20–2:10 | **Demo:** una señal se vuelve acusación; otra se descarta con su razón. | 5 |
| 2:10–2:40 | El case file: rastro del dinero, monto y pistas descartadas. | 6 |
| 2:40–3:00 | Resultados en casos reservados: recall y falsas acusaciones. | 7 |

## Si los jueces preguntan

| Pregunta | Respuesta corta |
|---|---|
| ¿Por qué confiar en este número? | Es la suma de registros citados, reconciliada al 2% y verificada por el validador oficial. |
| ¿Por qué no marcaste al proveedor X? | Está en las pistas descartadas con la razón exacta y las consultas que se hicieron. |
| ¿Qué pasa si no hay nada que encontrar? | Cero hallazgos es un resultado válido; las señales quedan como pistas cerradas. |
| ¿Por qué no usar un LLM para detectar? | Para que el resultado sea reproducible, gratuito y cada afirmación tenga una fila detrás. |
| ¿Qué no detecta? | Reglas aún no implementadas (p. ej. Benford) y no hay todavía un revisor adversarial. |
