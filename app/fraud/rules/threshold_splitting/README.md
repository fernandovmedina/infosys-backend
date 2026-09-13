# Módulo 4 · Threshold splitting (fraccionamiento de compras)

El **fraccionamiento** consiste en partir una compra grande en varias órdenes más chicas para
que ninguna rebase el monto que exige autorización superior o conjunta. Así una sola persona
aprueba lo que debió pasar por más controles. Es una evasión del control interno de compras.

Cada coincidencia es una **señal**. `SAME_APPROVER_SPLIT` es `autosuficiente` según la spec,
pero el ensamblador igual pide dos familias de evidencia para acusar, porque varias órdenes
seguidas al mismo proveedor también pueden ser obligaciones distintas y legítimas.

## Resumen

| Regla | Pregunta que responde | Severidad | Archivo |
|---|---|---|---|
| `SAME_APPROVER_SPLIT` | ¿La misma persona autorizó varias órdenes al mismo proveedor en una semana que juntas superan el umbral? | alta | `same_approver_split.py` |
| `CONTRACT_SPLIT_INTO_POS` | ¿Un solo contrato vale lo mismo que la suma de varias órdenes emitidas al arrancar? | alta | `contract_split_into_pos.py` |

---

## `SAME_APPROVER_SPLIT`

**Qué busca:** ráfagas de 2 o más órdenes de compra al mismo proveedor dentro de 7 días, todas
con el mismo `approver`, cuya suma supera $50,000.

**Por qué es sospechoso:** una compra real suele pedirse en una sola orden. Varias órdenes
casi consecutivas, aprobadas por la misma persona, sugieren que se partió el monto para
quedar bajo el límite de autorización.

**Cómo lo detecta:**
- Marca como inicio de ráfaga cada orden sin otra orden previa del mismo proveedor y
  aprobador en los 7 días anteriores (así las sub-ventanas de una misma ráfaga no se repiten).
- Suma las órdenes del proveedor desde ese inicio hasta 7 días después.
- Se queda con las ventanas de al menos 2 órdenes, un solo aprobador y suma mayor al umbral.

**Parámetros:** `dias_ventana = 7`, `umbral_monto = 50000.0`.

**Qué reporta:** una fila por ráfaga. `entity_id` = `vendor_rfc`; `evidence_id` = `po_id` que
inicia la ventana; `monto` = suma de la ventana. Columnas extra: `approver`,
`num_ordenes_en_ventana`, `monto_acumulado_ventana`, `approver_es_solicitante`,
`ultima_fecha`, `evidence_ids_relacionados` (todas las órdenes).

**Ojo:** dispara igual con órdenes independientes que tienen su propio contrato (el decoy
típico). Por sí sola no distingue fraccionamiento de compras recurrentes; la corrobora
`CONTRACT_SPLIT_INTO_POS`.

## `CONTRACT_SPLIT_INTO_POS`

**Qué busca:** contratos cuyo valor coincide (±2 %) con la suma de 2 o más órdenes de compra del
mismo proveedor emitidas en los primeros 7 días del contrato, cada una por menos que el contrato.

**Por qué es sospechoso:** el contrato documenta **una** obligación por el total, pero se pidió
en pedazos. Es evidencia independiente de la anterior: cruza `contracts` contra
`purchase_orders` en vez de mirar solo las órdenes.

**Cómo lo detecta:**
- Para cada contrato, junta las órdenes del mismo RFC con fecha entre `start_date` y
  `start_date + 7 días` y monto menor al valor del contrato.
- Se queda con los contratos con al menos 2 órdenes cuya suma cae dentro de la tolerancia.

**Parámetros:** `dias_ventana = 7`, `tolerancia_pct = 0.02`.

**Qué reporta:** una fila por contrato. `entity_id` = `vendor_rfc`; `evidence_id` =
`contract_id`; `monto` = valor del contrato. Columnas extra: `num_ordenes`, `suma_ordenes`,
`evidence_ids_relacionados` (órdenes), `aprobadores`, `alcance_contrato`.

**Ojo:** no dispara si cada orden tiene su propio contrato (ninguna suma de varias coincide con
uno solo). Un contrato marco cuyo total se consume con órdenes al arranque también dispararía;
revisar `alcance_contrato`.

---

Las columnas del contrato de salida (`rule_id` … `monto`) se explican en el README del módulo 3.
