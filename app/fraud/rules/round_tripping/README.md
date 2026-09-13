# Módulo 3 · Round tripping (dinero que da la vuelta)

El **round tripping** consiste en sacar dinero de la empresa y hacerlo regresar, directamente
o pasando por intermediarios, para simular operaciones que no existieron. En el camino suele
quedarse una pequeña "comisión" con quien presta sus cuentas o sus facturas. El resultado
son ingresos o gastos inflados sin sustancia económica, justo la falta de *materialidad* que
el SAT persigue con el Art. 69-B del Código Fiscal de la Federación (CFF).

Las reglas de este módulo buscan ciclos de dinero en `bank_txns`, facturación espejo en
`invoices` y pagos a proveedores sospechosos que suelen iniciar el ciclo. Cada coincidencia
es una **señal** para revisar, no una acusación: todas las reglas son `presuntiva`, es
decir, necesitan otra evidencia para sostener un hallazgo.

## Resumen

| Regla | Pregunta que responde | Severidad | Archivo |
|---|---|---|---|
| `BANK_CYCLE_2NODE` | ¿Una cuenta nos devolvió casi el mismo dinero que le enviamos poco antes? | alta | `bank_cycle_2node.py` |
| `BANK_CYCLE_NNODE` | ¿El dinero regresó a su origen tras pasar por 2 o más cuentas intermedias? | alta | `bank_cycle_nnode.py` |
| `CYCLE_LEAKAGE_RATE` | ¿Alguna cuenta participa en ciclos repetidos quedándose siempre una comisión pequeña? | alta | `cycle_leakage_rate.py` |
| `INVOICE_BIDIRECTIONAL` | ¿Dos empresas se facturan mutuamente montos parecidos? | media | `invoice_bidirectional.py` |
| `OUTBOUND_TO_SUSPECT_ENTITY` | ¿Transferimos dinero a la cuenta de un proveedor EFOS o con CLABE compartida? | alta / media | `outbound_to_suspect_entity.py` |
| `BANK_TXN_NOT_IN_LEDGER` | ¿Entró o salió dinero de la cuenta de la empresa sin ningún asiento contable? | alta / media | `bank_txn_not_in_ledger.py` |

> **Glosario rápido.** **CLABE**: número de cuenta bancaria interbancaria de 18 dígitos; en
> este módulo es el "nodo" del grafo de pagos. **RFC**: clave fiscal del contribuyente.
> **CFDI**: factura electrónica; su identificador es el `uuid`. **EFOS**: empresa que factura
> operaciones simuladas (ver módulo 1). **Tasa de fuga**: `1 - monto_retorno / monto_salida`,
> la parte del dinero que no regresó (0.03 = se quedó el 3 %).

> **Nota de diseño.** La spec deja estas reglas fuera de alcance y sugiere resolverlas con
> `networkx`. Aquí se implementaron en SQL puro con CTE recursivos de DuckDB, que permiten
> exigir orden cronológico entre saltos. Lógica, severidades y umbrales se decidieron al
> implementar; no vienen de la spec.

---

## `BANK_CYCLE_2NODE`

**Qué busca:** una cuenta A paga a B y, dentro de 30 días, B le devuelve a A un monto
similar (±10 %).

**Por qué es sospechoso:** un pago real a un proveedor no regresa. Si el dinero vuelve casi
íntegro en pocos días, la operación probablemente solo existió para generar el movimiento
(y la factura que lo respalda).

**Cómo lo detecta:**
- Toma los movimientos válidos de `bank_txns` (fecha válida, ambas CLABE presentes y
  distintas, monto positivo).
- Cruza cada salida A → B con los movimientos B → A de la misma fecha o posteriores.
- Se queda con los que regresan en `dias_ventana` días o menos y cuyo monto está dentro
  de ±`tolerancia_pct` del monto de salida.

**Parámetros:** `dias_ventana = 30`, `tolerancia_pct = 0.10`.

**Qué reporta:** una fila por par (salida, retorno). `entity_id` = CLABE que recibió y
devolvió el dinero (aquí no es un RFC); `evidence_id` = `txn_id` de la salida; `monto` =
monto de salida. Columnas extra: `clabe_origen`, `txn_id_retorno`, `fecha_retorno`,
`monto_retorno`, `dias_hasta_retorno`, `tasa_fuga`.

**Ejemplo:** T1: A → B por $100,000 el 1-mar-2026; T2: B → A por $97,000 el 10-mar → 9 días,
fuga 0.03 → señal alta.

**Ojo:** si una salida tiene varios retornos compatibles, genera una fila por cada uno, y un
mismo retorno puede emparejarse con varias salidas; no sumes `monto` sin deduplicar. La
`tasa_fuga` es negativa cuando regresa más de lo que salió. Si ambos movimientos son del
mismo día, el par se reporta una sola vez (la salida es la de `txn_id` menor).

## `BANK_CYCLE_NNODE`

**Qué busca:** ciclos de 3 a 5 cuentas (A → B → C → … → A) donde cada salto ocurre en orden
cronológico, todo dentro de 60 días desde el primer movimiento, y cada salto tiene un monto
similar (±10 %) al salto anterior.

**Por qué es sospechoso:** es el mismo esquema que `BANK_CYCLE_2NODE`, pero con
intermediarios para que no sea evidente que el dinero regresó al origen.

**Cómo lo detecta:**
- Parte de cada movimiento de `bank_txns` y lo extiende salto a salto con un CTE recursivo:
  el siguiente movimiento debe salir de la cuenta donde llegó el anterior, en la misma
  fecha o después.
- No repite cuentas intermedias y deja de extender el camino cuando vuelve al origen.
- Se queda con los caminos cerrados de 3 saltos o más (los de 2 son de `BANK_CYCLE_2NODE`).
- Ancla cada ciclo en su movimiento más antiguo (fecha, `txn_id`) para no reportar el mismo
  ciclo varias veces empezando desde otra cuenta.

**Parámetros:** `max_nodos = 5` (máximo de saltos, igual al número de cuentas del ciclo),
`dias_ventana = 60`, `tolerancia_pct = 0.10`.

**Qué reporta:** una fila por ciclo. `entity_id` = CLABE que recibió el primer movimiento;
`evidence_id` = `txn_id` inicial; `fecha_deteccion` = fecha del primer movimiento;
`monto` = monto inicial. Columnas extra: `clabe_origen`, `num_nodos`, `ruta_clabes`,
`txns_ciclo` (todos los `txn_id` del ciclo en orden), `monto_retorno`, `dias_ciclo`, `tasa_fuga`.

**Ejemplo:** A → C $100,000 (1-abr), C → D $92,000 (5-abr), D → A $85,000 (12-abr) →
ruta `A -> C -> D -> A`, 11 días, fuga 0.15 → señal alta.

**Ojo:** la tolerancia se aplica **entre saltos consecutivos**, no contra el monto inicial,
así que la fuga total puede superar `tolerancia_pct` (en el ejemplo, 15 % con tolerancia de
10 %). La búsqueda de caminos crece rápido con muchos movimientos entre las mismas cuentas;
subir `max_nodos` o `dias_ventana` puede volver lenta la regla.

## `CYCLE_LEAKAGE_RATE`

**Qué busca:** cuentas por las que el dinero circula en al menos 2 ciclos y regresa casi
íntegro: tasa de fuga promedio de 10 % o menos.

**Por qué es sospechoso:** una fuga pequeña y constante es la "comisión" del intermediario
que presta su cuenta o vende facturas. Un ciclo aislado puede ser casualidad; varios con la
misma comisión son un patrón.

**Cómo lo detecta:**
- Busca ciclos de 2 a `max_nodos` cuentas con la misma lógica temporal que
  `BANK_CYCLE_NNODE` (duplicada a propósito: las reglas no dependen entre sí).
- Agrupa los ciclos por la cuenta que recibe el primer movimiento (la contraparte).
- Señala las contrapartes con al menos `min_ciclos` ciclos y fuga promedio ≤ `fuga_maxima`.

**Parámetros:** `max_nodos = 5`, `dias_ventana = 60`, `tolerancia_pct = 0.10`,
`min_ciclos = 2`, `fuga_maxima = 0.10`.

**Qué reporta:** **una fila por contraparte** (señal agregada, no por transacción).
`entity_id` = CLABE de la contraparte; `evidence_id` = `txn_id` inicial del ciclo más
antiguo; `fecha_deteccion` = fecha de ese ciclo; `monto` = total que salió en todos sus
ciclos. Columnas extra: `monto_retorno_total`, `tasa_fuga_promedio`, `tasa_fuga_stddev`
(una desviación baja indica comisión constante), `num_ciclos`, `clabes_origen`,
`evidence_ids_relacionados` (todos los `txn_id` iniciales).

**Ejemplo:** A → B $100,000 regresa $97,000 (fuga 0.03) y A → B $50,000 regresa $49,000
(fuga 0.02) → B con 2 ciclos, fuga promedio 0.025 → señal alta.

**Ojo:** un retorno negativo (regresa más de lo que salió) también cumple `fuga_maxima` y
baja el promedio. Si una salida tiene varios retornos compatibles, cuenta como varios
ciclos e infla `num_ciclos` y `monto`. Estos mismos ciclos también aparecen, uno por uno,
en `BANK_CYCLE_2NODE` y `BANK_CYCLE_NNODE`.

## `INVOICE_BIDIRECTIONAL`

**Qué busca:** A factura a B y B factura a A por un total similar (±20 %) dentro de 90 días.

**Por qué es sospechoso:** un ingreso y un gasto espejo con la misma contraparte se
compensan entre sí. Es el round tripping documental: las facturas justifican movimientos
que en el fondo no cambian nada, salvo inflar ingresos o deducciones.

**Cómo lo detecta:**
- Toma las facturas de `invoices` con fecha válida, emisor y receptor presentes y distintos,
  y total positivo.
- Cruza cada factura A → B con las facturas B → A de la misma fecha o posteriores.
- Se queda con las que caen en `dias_ventana` días o menos y cuyo total está dentro de
  ±`tolerancia_pct` del total de la primera.

**Parámetros:** `dias_ventana = 90`, `tolerancia_pct = 0.20`.

**Qué reporta:** una fila por par de facturas, anclada en la más antigua. `entity_id` = RFC
emisor de la factura más antigua; `evidence_id` = su `uuid`; `monto` = su total. Columnas
extra: `rfc_contraparte`, `uuid_espejo`, `fecha_espejo`, `monto_espejo`,
`dias_entre_facturas`, `status_factura`, `status_espejo`.

**Ejemplo:** `AAAA010101AA1` factura $116,000 a `BBBB020202BB2` el 10-ene-2026; `BBBB020202BB2`
le factura $110,000 el 20-feb → 41 días → señal media.

**Ojo:** en la contabilidad de la empresa auditada, uno de los dos RFC suele ser la propia
empresa; si ella facturó primero, `entity_id` será su RFC y la contraparte a revisar está en
`rfc_contraparte`. Incluye facturas canceladas; se distinguen por `status_factura` y
`status_espejo`. Como la tolerancia es amplia, relaciones legítimas de compra-venta mutua
(p. ej. cliente que también es proveedor) pueden disparar la regla.

## `OUTBOUND_TO_SUSPECT_ENTITY`

**Qué busca:** transferencias bancarias a la CLABE de un proveedor sospechoso: su RFC está
en la lista EFOS del SAT o su CLABE la comparten varios RFC.

**Por qué es sospechoso:** es la salida de dinero que suele iniciar un esquema de round
tripping. Complementa al módulo 1: allá se señala la factura, aquí el pago que la liquidó.

**Cómo lo detecta:**
- Relaciona el destino de cada movimiento (`bank_txns.to_clabe`) con la CLABE del proveedor
  en `vendors`.
- Revisa si el RFC de ese proveedor está en `efos_list` (cualquier status) y si su CLABE está
  registrada por más de un RFC.
- Señala el movimiento si se cumple al menos una de las dos condiciones.

**Parámetros:** ninguno.

**Qué reporta:** una fila por (transacción, proveedor dueño de la CLABE). `entity_id` = RFC
del proveedor; `evidence_id` = `txn_id`; `monto` = monto transferido. **Severidad dinámica:**
`alta` si el RFC es EFOS `definitivo`; `media` si es EFOS `presunto` o solo tiene CLABE
compartida. Columnas extra: `motivo_sospecha` (p. ej. `EFOS definitivo; CLABE compartida por 2 RFC`),
`razon_social`, `destino_clabe`, `origen_clabe`, `efos_status`, `efos_publication_date`,
`referencia`, `canal`.

**Ejemplo:** transferencia SPEI por $116,000 a la CLABE `111111111111111111`, registrada por
`AAAA010101AA1` (EFOS `definitivo`) → señal alta.

**Ojo:** si la CLABE la comparten 3 proveedores, **una misma transferencia genera 3 filas**
(una por RFC); no sumes `monto` sin deduplicar por `evidence_id`. No compara la fecha del
pago contra la de publicación EFOS: también señala pagos anteriores a la publicación. Si un
RFC aparece más de una vez en `efos_list`, sus transferencias se duplican.

## `BANK_TXN_NOT_IN_LEDGER`

**Qué busca:** movimientos de la cuenta bancaria de la empresa que no tienen ningún renglón
en `ledger` por el mismo monto (cargo si es entrada, abono si es salida) dentro de ±3 días.

**Por qué es sospechoso:** en el round tripping el dinero regresa a la empresa por una cuenta
intermediaria y esa vuelta no se contabiliza. Un reembolso legítimo sí se registra (cargo a
bancos y reversión del gasto). Es evidencia independiente de los ciclos: compara el banco
contra la contabilidad, no el grafo de pagos.

**Cómo lo detecta:**
- Toma como cuenta de la empresa la CLABE que participa en más movimientos de `bank_txns`.
- Para cada movimiento que entra o sale de esa cuenta, busca en `ledger` un renglón de
  cualquier cuenta contable con el monto en el lado correcto (±`tolerancia_monto` pesos) y
  fecha a ±`dias_tolerancia` días.
- Señala los movimientos sin ningún renglón compatible.

**Parámetros:** `dias_tolerancia = 3`, `tolerancia_monto = 0.01`.

**Qué reporta:** una fila por movimiento. `entity_id` = CLABE de la contraparte (no es un
RFC); `evidence_id` = `txn_id`; `monto` = monto del movimiento. Severidad `alta` si es entrada
y `media` si es salida. Columnas extra: `direccion`, `clabe_empresa`, `origen_clabe`,
`destino_clabe`, `referencia`, `canal`.

**Ojo:** la inferencia de la cuenta de la empresa falla si `bank_txns` trae varias cuentas
propias con volumen parecido. Como no exige la cuenta contable de bancos, un renglón con el
mismo monto por coincidencia oculta el movimiento (falso negativo, no falso positivo).

---

## Cómo leer una señal

Todas las reglas devuelven estas 8 columnas, en este orden, seguidas de sus columnas extra.

| Columna | Significado |
|---|---|
| `rule_id` | Nombre de la regla que generó la señal |
| `source_table` | Tabla donde está el registro de evidencia (`bank_txns` o `invoices`) |
| `entity_id` | A quién señala: una CLABE en las reglas de ciclos bancarios; un RFC en `INVOICE_BIDIRECTIONAL` y `OUTBOUND_TO_SUSPECT_ENTITY` |
| `evidence_id` | Registro exacto que sustenta la señal (`txn_id` del movimiento o `uuid` de la factura) |
| `fecha_deteccion` | Fecha del hecho detectado (en ciclos, la del primer movimiento) |
| `severidad` | `alta`, `media` o `baja` |
| `autosuficiencia` | `autosuficiente` (basta por sí sola) o `presuntiva` (requiere más evidencia) |
| `monto` | Monto en pesos asociado (en ciclos, lo que salió; en `CYCLE_LEAKAGE_RATE`, el total acumulado) |

Los RFC se comparan sin distinguir mayúsculas ni espacios, así que `" aaaa010101aa1 "` y
`AAAA010101AA1` cuentan como el mismo contribuyente. Las CLABE solo se limpian de espacios.
Los movimientos o facturas con fecha inválida se ignoran.

## Fuera de este módulo

- La detección de ciclos considera todas las cuentas de `bank_txns`, no solo las de la
  empresa auditada; relacionar cada CLABE con su RFC (`vendors`, `employees`) queda para el
  ensamblador de Findings.
