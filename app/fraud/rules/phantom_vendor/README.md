# Módulo 1 · Proveedores fantasma (EFOS / EDOS)

Una **empresa fantasma** vende facturas, no bienes ni servicios. El SAT la llama **EFOS**
(Empresa que Factura Operaciones Simuladas); a quien compra y deduce esas facturas le llama
**EDOS** (Empresa que Deduce Operaciones Simuladas). El Art. 69-B del Código Fiscal de la
Federación (CFF) permite al SAT publicar listas de estos contribuyentes y quitarle el efecto
fiscal a sus facturas.

Las reglas de este módulo buscan indicios de que la empresa auditada le compra a un proveedor
fantasma. Cada coincidencia es una **señal** para revisar, no una acusación: todas las reglas
son `presuntiva`, es decir, necesitan otra evidencia para sostener un hallazgo.

## Resumen

| Regla | Pregunta que responde | Severidad | Archivo |
|---|---|---|---|
| `EFOS_DIRECT_MATCH` | ¿Le compramos a un proveedor que el SAT ya confirmó como EFOS? | alta | `efos_direct_match.py` |
| `EFOS_PRESUNTO_MATCH` | ¿Le compramos a un proveedor que el SAT investiga como posible EFOS? | media | `efos_presunto_match.py` |
| `EFOS_POST_DATED` | ¿Tenemos facturas de un EFOS emitidas antes de que el SAT lo publicara? | media | `efos_post_dated.py` |
| `VENDOR_SHORT_LIFECYCLE` | ¿Algún proveedor empezó a facturar casi recién creado? | media | `vendor_short_lifecycle.py` |
| `INVOICE_NO_PO_NO_CONTRACT` | ¿Pagamos facturas grandes a proveedores sin orden de compra ni contrato? | media | `invoice_no_po_no_contract.py` |
| `SHARED_CLABE_MULTI_RFC` | ¿Varios proveedores distintos cobran en la misma cuenta bancaria? | alta | `shared_clabe_multi_rfc.py` |

> **Glosario rápido.** **RFC**: clave fiscal del contribuyente (12 caracteres si es empresa,
> 13 si es persona). **CFDI**: factura electrónica; su identificador es el `uuid`.
> **CLABE**: número de cuenta bancaria interbancaria de 18 dígitos.

---

## `EFOS_DIRECT_MATCH`

**Qué busca:** facturas emitidas por un RFC que está en la lista EFOS con status `definitivo`.

**Por qué es sospechoso:** el SAT ya concluyó que ese proveedor simula operaciones. Sus
facturas no se pueden deducir salvo que la empresa demuestre que la operación sí existió.

**Cómo lo detecta:** cruza el emisor de cada factura (`invoices`) contra la lista del SAT
(`efos_list`) y se queda con los de status `definitivo`.

**Qué reporta:** una fila por factura. `entity_id` = RFC del emisor; `evidence_id` = `uuid`
de la factura. Columnas extra: `efos_status`, `efos_publication_date`.

**Ejemplo:** factura INV-1 por $116,000 de `AAAA010101AA1`, que aparece como `definitivo`
→ señal alta.

**Ojo:** es la señal más fuerte del módulo, pero sigue siendo `presuntiva`. Las facturas
anteriores a la publicación también aparecen en `EFOS_POST_DATED`.

## `EFOS_PRESUNTO_MATCH`

**Qué busca:** lo mismo que la anterior, pero con proveedores en status `presunto`.

**Por qué es sospechoso:** el SAT abrió el procedimiento contra ese proveedor pero aún no
lo confirma. Es una alerta temprana para frenar pagos o pedir soporte de la operación.

**Cómo lo detecta:** mismo cruce `invoices` ↔ `efos_list`, filtrando status `presunto`.

**Qué reporta:** una fila por factura, con las mismas columnas que `EFOS_DIRECT_MATCH`.

**Ojo:** el proveedor todavía puede desvirtuar la presunción ante el SAT y salir de la lista.

## `EFOS_POST_DATED`

**Qué busca:** facturas de un EFOS `definitivo` emitidas **antes** de que el SAT lo publicara.

**Por qué es sospechoso:** cuando la empresa recibió la factura, el proveedor todavía no
estaba en la lista. El efecto fiscal se pierde de todas formas, así que hay que revisar
deducciones de ejercicios pasados.

**Cómo lo detecta:**
- Mismo cruce que `EFOS_DIRECT_MATCH`.
- Además exige que la fecha de publicación sea posterior a la fecha de la factura.

**Qué reporta:** una fila por factura. Columna extra clave: `dias_publicacion_posterior`
(días entre la factura y la publicación).

**Ejemplo:** factura del 10-ene-2026; proveedor publicado el 15-feb-2026 → 36 días → señal.

**Ojo:** si alguna de las dos fechas no es válida, la factura se ignora.

## `VENDOR_SHORT_LIFECYCLE`

**Qué busca:** proveedores que emiten su primera factura a menos de 30 días de su alta.

**Por qué es sospechoso:** las empresas fantasma se crean para facturar de inmediato y
desaparecer. Un proveedor legítimo rara vez vende montos importantes en su primer mes.

**Cómo lo detecta:**
- Para cada proveedor (`vendors`) toma su factura más antigua (`invoices`).
- Calcula los días entre su fecha de alta (`registered_date`) y esa factura.
- Señala si son menos de `dias_umbral`.

**Parámetros:** `dias_umbral = 30`.

**Qué reporta:** **una fila por proveedor**. `entity_id` = RFC; `evidence_id` = `uuid` de
su primera factura; `monto` = total de esa factura. Columnas extra: `dias_hasta_primera_factura`,
`fecha_registro`, `razon_social`, `monto_acumulado` (todo lo que ha facturado) y `num_facturas`.

**Ejemplo:** alta el 1-ene-2026, primera factura por $116,000 el 10-ene → 9 días → señal.

**Ojo:** si la factura es anterior al alta, los días salen negativos y también se señala
(es aún más raro). Un proveedor nuevo pero legítimo también dispara la regla.

## `INVOICE_NO_PO_NO_CONTRACT`

**Qué busca:** facturas mayores a $50,000 cuyo emisor no tiene ninguna orden de compra
ni ningún contrato con la empresa.

**Por qué es sospechoso:** sin orden de compra ni contrato no hay evidencia de que la
relación comercial exista (falta de *materialidad*), que es justo lo que el SAT revisa en
operaciones simuladas.

**Cómo lo detecta:**
- Busca el RFC del emisor en `purchase_orders` y en `contracts`.
- Señala la factura si el RFC no aparece en ninguna de las dos y el total supera `monto_minimo`.

**Parámetros:** `monto_minimo = 50000.0`.

**Qué reporta:** una fila por factura. `entity_id` = RFC del emisor; `evidence_id` = `uuid`.
Columnas extra: `concepto`, `status_factura`.

**Ojo:** la revisión es por proveedor, no por factura: basta **una** orden de compra de
cualquier monto para que ninguna factura de ese proveedor se señale. Incluye facturas
canceladas; se distinguen por `status_factura`.

## `SHARED_CLABE_MULTI_RFC`

**Qué busca:** una misma CLABE registrada por dos o más proveedores con RFC distinto.

**Por qué es sospechoso:** empresas distintas no deberían cobrar en la misma cuenta. Suele
indicar una red de empresas fachada controlada por la misma persona.

**Cómo lo detecta:** agrupa el catálogo de proveedores (`vendors`) por CLABE y se queda con
las que tienen más de un RFC.

**Qué reporta:** **una fila por CLABE**. `entity_id` = la CLABE (aquí no es un RFC);
`evidence_id` = el primer RFC en orden alfabético; `fecha_deteccion` = el alta más reciente
del grupo; `monto` vacío. Columnas extra: `rfcs_involucrados`, `num_rfcs`, `razones_sociales`.

**Ejemplo:** `AAAA010101AA1` y `BBBB020202BB2` registran la CLABE `111111111111111111` → señal alta.

**Ojo:** puede haber casos legítimos, como empresas del mismo grupo que comparten tesorería.

---

## Cómo leer una señal

Todas las reglas devuelven estas 8 columnas, en este orden, seguidas de sus columnas extra.

| Columna | Significado |
|---|---|
| `rule_id` | Nombre de la regla que generó la señal |
| `source_table` | Tabla donde está el registro de evidencia |
| `entity_id` | A quién señala: normalmente un RFC (en `SHARED_CLABE_MULTI_RFC`, una CLABE) |
| `evidence_id` | Registro exacto que sustenta la señal (`uuid` de factura o RFC de proveedor) |
| `fecha_deteccion` | Fecha del hecho detectado |
| `severidad` | `alta`, `media` o `baja` |
| `autosuficiencia` | `autosuficiente` (basta por sí sola) o `presuntiva` (requiere más evidencia) |
| `monto` | Monto en pesos asociado; vacío si la regla no tiene uno |

Los RFC se comparan sin distinguir mayúsculas ni espacios, así que `" aaaa010101aa1 "` y
`AAAA010101AA1` cuentan como el mismo proveedor.

## Fuera de este módulo

- `VENDOR_CATEGORY_MISMATCH` (el concepto facturado no corresponde al giro del proveedor) y
  `VENDOR_GENERIC_CONCEPT` (conceptos vagos como "servicios varios") necesitan analizar texto
  libre. Se resolverán en un módulo aparte de NLP.
