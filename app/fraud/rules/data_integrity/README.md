# Módulo 6 · Integridad de datos (capa 1)

Antes de buscar fraude hay que confirmar que los datos se pueden cruzar. Si una póliza no
cuadra, un RFC está mal capturado o una CLABE tiene un dígito de menos, las demás reglas
fallan en silencio: el proveedor EFOS no aparece en la lista, el pago no se liga a su
factura y el ciclo de dinero no se cierra. Por eso la spec pide implementar estas reglas
**primero**: son prerrequisito de todos los demás módulos.

A diferencia de los otros módulos, aquí todas las reglas son `autosuficiente`: el defecto
se comprueba directamente en el dato, sin necesidad de otra evidencia. Que un dato esté mal
no prueba fraude, pero sí es un hallazgo por sí mismo (contabilidad o catálogo que no
cumple el formato exigido) y a veces la forma de ocultarlo.

## Resumen

| Regla | Pregunta que responde | Severidad | Archivo |
|---|---|---|---|
| `LEDGER_UNBALANCED_ENTRY` | ¿Hay pólizas donde el debe no es igual al haber? | alta | `ledger_unbalanced_entry.py` |
| `ORPHAN_INVOICE_UUID` | ¿Hay asientos contables que citan una factura que no existe? | alta | `orphan_invoice_uuid.py` |
| `MALFORMED_RFC` | ¿Hay RFC con longitud o caracteres inválidos? | media | `malformed_rfc.py` |
| `CLABE_INVALID_LENGTH` | ¿Hay proveedores o empleados con una CLABE que no tiene 18 dígitos? | media | `clabe_invalid_length.py` |

> **Glosario rápido.** **Póliza**: registro contable compuesto por varios asientos (cargos y
> abonos) que deben sumar lo mismo. **Debe / haber**: `debit` / `credit` del `ledger`.
> **RFC**: clave fiscal (12 caracteres si es empresa, 13 si es persona). **CFDI**: factura
> electrónica; su identificador es el `uuid`. **CLABE**: cuenta interbancaria de 18 dígitos.

---

## `LEDGER_UNBALANCED_ENTRY`

**Qué busca:** pólizas cuya suma de cargos (`debit`) difiere de la suma de abonos (`credit`)
por más de $0.01.

**Por qué es sospechoso:** la partida doble (NIF A-2; Art. 28 CFF sobre contabilidad) exige
que toda póliza cuadre. Un descuadre indica un error de captura, un asiento borrado o
modificado a mano, o un registro parcial que infla un gasto sin su contrapartida.

**Cómo lo detecta:**
- El `ledger` no tiene número de póliza, así que agrupa por `invoice_uuid` (normalizado con
  `UPPER(TRIM(...))`) + `date`, como indica la spec.
- Suma `debit` y `credit` de cada grupo, convertidos a `DOUBLE` para evitar descuadres falsos
  por redondeo de `REAL`.
- Señala los grupos donde la diferencia absoluta supera `tolerancia`.

**Parámetros:** `tolerancia = 0.01`.

**Qué reporta:** **una fila por grupo** (señal agregada). `entity_id` = el `invoice_uuid`
normalizado, o `SIN_UUID` si los asientos no citan factura; `evidence_id` = `entry_id` menor
del grupo; `monto` = diferencia absoluta. Columnas extra: `total_debe`, `total_haber`,
`diferencia` (con signo: positiva si sobran cargos), `num_asientos`,
`evidence_ids_relacionados` (todos los `entry_id`), `approvers`.

**Ejemplo:** el 15-feb-2026, factura `INV-1`: cargo gasto $80,000 + cargo IVA $12,800, abono
proveedores $90,000 → diferencia $2,800 → señal alta.

**Ojo:**
- Todos los asientos sin factura del mismo día forman **un solo grupo** `SIN_UUID`: pólizas
  distintas pueden compensarse entre sí (ocultando un descuadre) o mezclarse (dando una
  señal difícil de rastrear). Revisa `evidence_ids_relacionados`.
- Si una póliza real abarca varias fechas (registro y pago en días distintos), cada día se
  evalúa por separado y puede aparecer descuadrado aunque la póliza completa cuadre.
- La fecha se agrupa como texto, sin validar: `2026-02-15` y `2026-02-15 ` son grupos
  distintos, y las fechas vacías forman su propio grupo.
- Un asiento huérfano de un solo lado (solo cargo) también sale aquí, además de en
  `ORPHAN_INVOICE_UUID`.

## `ORPHAN_INVOICE_UUID`

**Qué busca:** asientos del `ledger` cuyo `invoice_uuid` no existe en `invoices`.

**Por qué es sospechoso:** un gasto registrado sin CFDI que lo soporte no es deducible
(Art. 27 fr. III y 29 CFF). Citar una factura inexistente puede ser un error de captura o
un intento de dar apariencia de soporte a un gasto que no lo tiene.

**Cómo lo detecta:**
- Toma los asientos con `invoice_uuid` no vacío.
- Los cruza contra `invoices.uuid` (ambos con `UPPER(TRIM(...))`) con `LEFT JOIN`.
- Se queda con los que no encuentran factura.

**Parámetros:** ninguno.

**Qué reporta:** una fila por asiento. `entity_id` = el `invoice_uuid` huérfano (aquí no es
un RFC); `evidence_id` = `entry_id`; `monto` = el mayor entre `debit` y `credit`. Columnas
extra: `cuenta`, `nombre_cuenta`, `descripcion`, `approver`.

**Ejemplo:** asiento 4 del 16-feb-2026, cargo de $5,000 a la cuenta 5000 citando `INV-999`,
que no está en `invoices` → señal alta.

**Ojo:** los asientos sin `invoice_uuid` no se revisan (el campo es opcional en el esquema).
Una factura **cancelada** sí existe en `invoices`, así que sus asientos no se señalan aquí.
Si varios asientos citan el mismo uuid huérfano, sale una fila por cada uno; `entity_id`
conserva las mayúsculas originales.

## `MALFORMED_RFC`

**Qué busca:** RFC vacíos, con longitud distinta de 12 o 13 caracteres, o con caracteres
fuera de `A-Z`, `0-9`, `Ñ` y `&`.

**Por qué es sospechoso:** un RFC mal formado no puede cruzarse contra la lista EFOS ni
contra órdenes de compra y contratos, así que un proveedor fantasma puede escapar de las
demás reglas con solo tener un carácter de más. `Ñ` y `&` se aceptan porque el SAT los usa
en RFC reales.

**Cómo lo detecta:**
- Junta en una sola consulta (`UNION ALL`) los RFC de `vendors.rfc`, `invoices.issuer_rfc`,
  `invoices.receiver_rfc` y `efos_list.rfc`.
- Valida cada valor tras `UPPER(TRIM(...))`, igual que lo comparan las demás reglas.
- Asigna el primer motivo que aplique, en orden: `vacío`, `longitud N`, `caracteres inválidos`.

**Parámetros:** ninguno.

**Qué reporta:** una fila por valor inválido. `source_table` = tabla real de origen;
`entity_id` = RFC normalizado (o `SIN_RFC` si está vacío); `evidence_id` = `uuid` en
`invoices`, el RFC original en `vendors` y `efos_list`; `fecha_deteccion` = fecha de alta,
emisión o publicación según la tabla; `monto` = `total` en `invoices`, vacío en las demás.
Columnas extra: `columna_origen` (`rfc`, `issuer_rfc` o `receiver_rfc`), `rfc_original`, `motivo`.

**Ejemplo:** factura `INV-1` con `issuer_rfc` = `AAA010101AA` (11 caracteres) → motivo
`longitud 11` → señal media.

**Ojo:**
- Solo valida longitud y caracteres, no la estructura (letras + fecha + homoclave):
  `123456789012` pasa como válido.
- Un espacio **interno** (`AAAA 010101A`) cuenta como carácter inválido; los espacios de
  los extremos y las minúsculas no se señalan porque se normalizan.
- Una misma factura puede generar dos filas (emisor y receptor); no sumes `monto` sin
  deduplicar por `evidence_id`.
- Los RFC `NULL` en `vendors` y `efos_list` se excluyen porque ahí el RFC es la llave y la
  fila no sería rastreable. Una cadena vacía `''` sí se reporta, con `evidence_id` vacío.

## `CLABE_INVALID_LENGTH`

**Qué busca:** CLABE de proveedores y empleados vacías, con caracteres no numéricos o con
longitud distinta de 18 dígitos.

**Por qué es sospechoso:** una CLABE inválida rompe el cruce entre `bank_txns` y el
catálogo, así que los pagos a esa cuenta quedan sin dueño identificado y escapan de reglas
como `SHARED_CLABE_MULTI_RFC` u `OUTBOUND_TO_SUSPECT_ENTITY`.

**Cómo lo detecta:**
- Junta con `UNION ALL` las `bank_clabe` de `vendors` y `employees`.
- Valida cada valor tras `TRIM`, igual que lo cruzan las demás reglas.
- Asigna el primer motivo que aplique, en orden: `vacía`, `caracteres no numéricos`,
  `longitud N`.

**Parámetros:** ninguno.

**Qué reporta:** una fila por proveedor o empleado. `source_table` = `vendors` o
`employees`; `entity_id` = RFC normalizado del proveedor o `emp_id` del empleado;
`evidence_id` = RFC original o `emp_id`; `fecha_deteccion` = fecha de alta o de
contratación; `monto` vacío. Columnas extra: `clabe_original`, `motivo`.

**Ejemplo:** empleado `EMP:0001` con CLABE `0021 8000 1234 5678` → motivo
`caracteres no numéricos` → señal media.

**Ojo:** no valida el dígito verificador ni el código de banco, solo formato. Los espacios
internos o guiones cuentan como no numéricos, así que el motivo reportado no siempre dice
que además la longitud es incorrecta. Las filas con `rfc` o `emp_id` `NULL` se ignoran;
`fecha_deteccion` es la del alta, no la del día en que se detectó el problema.

---

## Cómo leer una señal

Todas las reglas devuelven estas 8 columnas, en este orden, seguidas de sus columnas extra.

| Columna | Significado |
|---|---|
| `rule_id` | Nombre de la regla que generó la señal |
| `source_table` | Tabla donde está el registro de evidencia (`ledger`, `invoices`, `vendors`, `efos_list` o `employees`) |
| `entity_id` | A quién señala: un RFC, un `emp_id`, o un `invoice_uuid` en las reglas del `ledger` (`SIN_UUID` / `SIN_RFC` si el valor falta) |
| `evidence_id` | Registro exacto que sustenta la señal (`entry_id`, `uuid`, RFC o `emp_id`) |
| `fecha_deteccion` | Fecha del registro con el defecto |
| `severidad` | `alta`, `media` o `baja` |
| `autosuficiencia` | `autosuficiente` (basta por sí sola) o `presuntiva` (requiere más evidencia) |
| `monto` | Monto en pesos asociado; vacío si la regla no tiene uno |

Los RFC y los uuid se comparan sin distinguir mayúsculas ni espacios en los extremos, así que
`" inv-1 "` e `INV-1` cuentan como la misma factura. Las CLABE solo se limpian de espacios.

## Fuera de este módulo

- Esta es la **capa 1**: formato y consistencia básica de cada tabla. No revisa duplicados,
  fechas mal formadas ni valores fuera de los catálogos (`status`, `channel`, etc.).
