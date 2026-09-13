# Módulo 5 · Revenue inflation (inflado de ingresos)

El **inflado de ingresos** registra ventas que no existieron para mostrar mejores resultados.
Una forma común: emitir facturas de venta, registrarlas como ingreso y cuenta por cobrar, y
luego cancelar el CFDI sin revertir el registro contable. El ingreso sigue en los libros aunque
la operación ya no existe, y la cuenta por cobrar nunca se cobra. La contabilidad debe
reflejar operaciones reales (Art. 28, fracción I CFF).

A diferencia de los demás esquemas, aquí quien comete el fraude es **la propia empresa**: el
ensamblador acusa su RFC además del cliente de las facturas (`ESQUEMAS_DE_LA_EMPRESA` en
`agente/catalogo.py`).

## Resumen

| Regla | Pregunta que responde | Severidad | Archivo |
|---|---|---|---|
| `INFLATE_AND_CANCEL` | ¿Hay facturas canceladas cuyo registro contable no se revirtió? | media | `inflate_and_cancel.py` |
| `AR_AGING_EXCESSIVE` | ¿Hay cuentas por cobrar abiertas hace más de 90 días sin ningún cobro? | media | `ar_aging_excessive.py` |

---

## `INFLATE_AND_CANCEL`

**Qué busca:** facturas con `status = 'cancelado'` cuyos renglones del `ledger` (ligados por
`invoice_uuid`) dejan saldo en alguna cuenta.

**Por qué es sospechoso:** una cancelación bien hecha lleva su póliza de reversión y deja
ingreso, IVA y cuentas por cobrar en cero. Si queda saldo, el ingreso cancelado sigue inflando
los resultados.

**Cómo lo detecta:**
- Suma abonos menos cargos por factura y cuenta contable.
- Se queda con las facturas canceladas que tienen al menos una cuenta con saldo distinto de
  cero (±`tolerancia_monto`).

**Parámetros:** `tolerancia_monto = 0.01`.

**Qué reporta:** una fila por factura. `entity_id` = `issuer_rfc`; `evidence_id` = `uuid`;
`monto` = total de la factura. Columnas extra: `receiver_rfc`, `concepto`,
`cuentas_con_saldo`, `saldos_pendientes` (p. ej. `4000 Ingresos por servicios: 57188.0`).

**Divergencia con la spec:** la spec reporta toda factura cancelada y sube la severidad si hay
fecha de cancelación en otro ejercicio. `invoices` no tiene fecha de cancelación, así que la
severidad queda en `media`, y en vez de marcar todas las canceladas se exige que no estén
revertidas: eso separa el fraude de la cancelación legítima.

## `AR_AGING_EXCESSIVE`

**Qué busca:** cuentas por cobrar de una factura (cuentas cuyo nombre contiene `cobrar`) con
saldo deudor pendiente y más de 90 días de antigüedad.

**Por qué es sospechoso:** una venta real se cobra. Una cuenta por cobrar que nunca se cierra
(ni por cobro ni por reversión) es indicio de que la venta no existió.

**Cómo lo detecta:**
- Suma cargos menos abonos a cuentas por cobrar por factura.
- Mide la antigüedad desde el primer registro hasta la **fecha de corte** del estate (la fecha
  más reciente del `ledger`), no contra hoy, para que el resultado sea el mismo en cada corrida.

**Parámetros:** `dias_umbral = 90`, `tolerancia_monto = 0.01`.

**Qué reporta:** una fila por factura con saldo abierto. `entity_id` = `receiver_rfc` (el
cliente que debe); `evidence_id` = `entry_id` del primer cargo a cuentas por cobrar;
`monto` = saldo pendiente. Columnas extra: `issuer_rfc`, `invoice_uuid`, `status_factura`,
`dias_abierta`, `fecha_corte`.

**Ojo:** depende de que el catálogo de cuentas nombre las cuentas por cobrar con la palabra
`cobrar`. Ventas a crédito largo legítimas también disparan si superan el umbral.

---

Las columnas del contrato de salida (`rule_id` … `monto`) se explican en el README del módulo 3.
