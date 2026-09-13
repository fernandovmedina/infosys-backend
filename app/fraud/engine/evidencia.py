"""
Evidencia de un Finding: qué registros cita (exhibits), qué prueba cada uno
(nota por regla), el rastro del dinero y el peso_amount reconciliado por tabla.
Todo es determinista: mismas señales y mismo estate producen el mismo texto.
"""

import math

from .catalogo import AMOUNT_COLUMN, ORDEN_TABLAS, PRIORIDAD_MONTO, TABLE_PK, TOLERANCIA_PESOS
from .entidades import Resolutor, format_entity_id
from .estate import Estate

# --- formato ------------------------------------------------------------------


def _num(valor) -> float | None:
    try:
        v = float(valor)
    except TypeError, ValueError:
        return None
    return None if math.isnan(v) else v


def pesos(valor) -> str:
    v = _num(valor)
    return "monto desconocido" if v is None else f"${v:,.2f}"


def _pct(valor) -> str:
    v = _num(valor)
    return "?" if v is None else f"{v:.1%}"


def _entero(valor) -> str:
    v = _num(valor)
    return "?" if v is None else str(int(v))


def _txt(valor) -> str:
    return (
        "no data"
        if valor is None or (isinstance(valor, float) and math.isnan(valor))
        else str(valor).strip()
    )


def _separar(texto, sep: str) -> list[str]:
    return [p.strip() for p in str(texto or "").split(sep) if p.strip()]


def llave_registro(tabla: str, record_id) -> tuple[str, str]:
    rid = str(record_id).strip()
    return (tabla, rid.upper() if tabla in ("vendors", "efos_list") else rid)


# --- citas: qué registros sustentan cada Signal y qué prueba cada uno -------------


class Citas:
    """Registros citados en orden de aparición, con los motivos de cada uno."""

    def __init__(self):
        self._motivos: dict[tuple[str, str], list[str]] = {}

    def agregar(
        self, tabla: str, record_id, motivo: str | None = None, solo_si_nuevo: bool = False
    ) -> None:
        """`solo_si_nuevo`: el motivo es contexto genérico y se omite si el registro ya tiene uno propio."""
        if record_id is None or str(record_id).strip() == "":
            return
        llave = llave_registro(tabla, record_id)
        if solo_si_nuevo and llave in self._motivos:
            return
        motivos = self._motivos.setdefault(llave, [])
        if motivo and motivo not in motivos:
            motivos.append(motivo)

    def items(self):
        return self._motivos.items()

    def __contains__(self, llave) -> bool:
        return llave in self._motivos


def citar_senal(citas: Citas, sig: dict) -> None:
    """Agrega el registro de evidencia del Signal y los relacionados de su contexto."""
    regla, ctx, tabla, eid = (
        sig["rule_id"],
        sig["contexto"],
        sig["source_table"],
        sig["evidence_id"],
    )

    if regla == "EFOS_DIRECT_MATCH":
        citas.agregar(
            tabla,
            eid,
            "issued by a taxpayer that SAT has listed as a definitive EFOS, so it has no tax effect",
        )
        citas.agregar("efos_list", sig["entity_id"])
    elif regla == "EFOS_PRESUNTO_MATCH":
        citas.agregar(tabla, eid, "issued by a taxpayer that SAT lists as a presumed EFOS")
        citas.agregar("efos_list", sig["entity_id"])
    elif regla == "EFOS_POST_DATED":
        citas.agregar(
            tabla,
            eid,
            f"issued {_entero(ctx.get('dias_publicacion_posterior'))} days before SAT listed the issuer as an EFOS",
        )
        citas.agregar("efos_list", sig["entity_id"])
    elif regla == "VENDOR_SHORT_LIFECYCLE":
        citas.agregar(
            tabla,
            eid,
            f"is the vendor's first invoice, issued {_entero(ctx.get('dias_hasta_primera_factura'))} days after registration",
        )
        citas.agregar(
            "vendors",
            sig["entity_id"],
            f"has invoiced {pesos(ctx.get('monto_acumulado'))} across {_entero(ctx.get('num_facturas'))} invoices since registration",
        )
    elif regla == "INVOICE_NO_PO_NO_CONTRACT":
        citas.agregar(
            tabla, eid, "its issuer has no purchase order or contract with the audited company"
        )
    elif regla == "SHARED_CLABE_MULTI_RFC":
        rfcs = _separar(ctx.get("rfcs_involucrados"), ",")
        for rfc in rfcs:
            otros = ", ".join(r for r in rfcs if r != rfc)
            citas.agregar("vendors", rfc, f"registered the same CLABE {sig['entity_id']} as {otros}")
    elif regla == "OUTBOUND_TO_SUSPECT_ENTITY":
        citas.agregar(
            tabla,
            eid,
            f"payment to {sig['entity_id']}, a vendor with {_txt(ctx.get('motivo_sospecha'))}",
        )
    elif regla == "PAYMENT_TO_EMPLOYEE_ACCOUNT":
        citas.agregar(
            tabla,
            eid,
            f"reached employee {sig['entity_id']}'s bank account ({_txt(ctx.get('nombre_empleado'))}, {_txt(ctx.get('puesto_empleado'))})",
        )
        citas.agregar("employees", sig["entity_id"])
    elif regla == "APPROVER_VENDOR_CONCENTRATION":
        uuids = _separar(ctx.get("evidence_ids_relacionados"), ",")
        for uuid in uuids:
            citas.agregar(
                "invoices",
                uuid,
                f"one of {len(uuids)} invoices from {_txt(ctx.get('vendor_rfc'))} approved by {sig['entity_id']}",
            )
    elif regla == "NO_SEGREGATION_OF_DUTIES":
        citas.agregar(tabla, eid, f"was both requested and approved by {sig['entity_id']}")
    elif regla == "PRICE_OUTLIER_BY_CATEGORY":
        citas.agregar(
            tabla,
            eid,
            f"its subtotal is {_num(ctx.get('z_score')) or 0:.1f} standard deviations from the {_txt(ctx.get('categoria'))} category average ({pesos(ctx.get('prom_categoria'))})",
        )
    elif regla == "BANK_CYCLE_2NODE":
        retorno = ctx.get("txn_id_retorno")
        citas.agregar(
            tabla,
            eid,
            f"outbound transfer that returned to its origin in {_entero(ctx.get('dias_hasta_retorno'))} days through transfer {_txt(retorno)} (leakage {_pct(ctx.get('tasa_fuga'))})",
        )
        citas.agregar(tabla, retorno, f"returns the funds from transfer {eid} to the origin")
    elif regla == "BANK_CYCLE_NNODE":
        for txn in _separar(ctx.get("txns_ciclo"), ","):
            citas.agregar(
                "bank_txns",
                txn,
                f"is a hop in cycle {_txt(ctx.get('ruta_clabes'))}, completed in {_entero(ctx.get('dias_ciclo'))} days",
            )
    elif regla == "CYCLE_LEAKAGE_RATE":
        for txn in _separar(ctx.get("evidence_ids_relacionados"), ","):
            citas.agregar(
                "bank_txns",
                txn,
                f"starts one of {_entero(ctx.get('num_ciclos'))} cycles involving {sig['entity_id']} with average leakage of {_pct(ctx.get('tasa_fuga_promedio'))}",
            )
    elif regla == "SAME_APPROVER_SPLIT":
        ordenes = _separar(ctx.get("evidence_ids_relacionados"), ",")
        for po in ordenes:
            citas.agregar(
                "purchase_orders",
                po,
                f"one of {len(ordenes)} orders to {sig['entity_id']} approved by {_txt(ctx.get('approver'))} "
                f"within less than a week, totaling {pesos(ctx.get('monto_acumulado_ventana'))}",
            )
    elif regla == "CONTRACT_SPLIT_INTO_POS":
        ordenes = _separar(ctx.get("evidence_ids_relacionados"), ",")
        citas.agregar(
            tabla,
            eid,
            f"its value is the sum of the {len(ordenes)} purchase orders {', '.join(ordenes)} ({pesos(ctx.get('suma_ordenes'))})",
        )
        for po in ordenes:
            citas.agregar("purchase_orders", po, f"is part of contract {eid}")
    elif regla == "INFLATE_AND_CANCEL":
        citas.agregar(
            tabla,
            eid,
            f"is cancelled, but its accounting entry was not reversed ({_txt(ctx.get('saldos_pendientes'))})",
        )
    elif regla == "AR_AGING_EXCESSIVE":
        citas.agregar(
            tabla,
            eid,
            f"accounts-receivable debit for invoice {_txt(ctx.get('invoice_uuid'))} that remains open "
            f"{_entero(ctx.get('dias_abierta'))} days later, as of {_txt(ctx.get('fecha_corte'))}",
        )
        citas.agregar(
            "invoices",
            ctx.get("invoice_uuid"),
            f"its receivable from {sig['entity_id']} was never collected",
            solo_si_nuevo=True,
        )
    elif regla == "BANK_TXN_NOT_IN_LEDGER":
        lado = "entered" if ctx.get("direccion") == "entrada" else "left"
        citas.agregar(
            tabla,
            eid,
            f"{lado} the company's account with no ledger entry for that amount (reference: {_txt(ctx.get('referencia'))})",
        )
    elif regla == "INVOICE_BIDIRECTIONAL":
        # Solo se cita una dirección: la factura espejo es el mismo dinero de regreso y
        # sumarla duplicaría el monto circulado. Se nombra en la nota para rastrearla.
        citas.agregar(
            tabla,
            eid,
            f"its mirror is invoice {_txt(ctx.get('uuid_espejo'))}, issued in the opposite direction "
            f"for {pesos(ctx.get('monto_espejo'))} {_entero(ctx.get('dias_entre_facturas'))} days later",
        )
    else:
        citas.agregar(tabla, eid, f"flagged by {regla}")


# --- exhibits ---------------------------------------------------------------------


def _describir(tabla: str, f: dict) -> str:
    if tabla == "invoices":
        return (
            f"Invoice {f['uuid']} from {_txt(f.get('issuer_rfc'))} to {_txt(f.get('receiver_rfc'))} "
            f"for {pesos(f.get('total'))} dated {_txt(f.get('issue_date'))} ({_txt(f.get('status'))})"
        )
    if tabla == "bank_txns":
        return (
            f"Transfer {f['txn_id']} for {pesos(f.get('amount'))} from CLABE {_txt(f.get('from_clabe'))} "
            f"to CLABE {_txt(f.get('to_clabe'))} on {_txt(f.get('date'))}"
        )
    if tabla == "purchase_orders":
        return (
            f"Purchase order {f['po_id']} to {_txt(f.get('vendor_rfc'))} for {pesos(f.get('amount'))} dated "
            f"{_txt(f.get('date'))}, requested by {_txt(f.get('requester'))} and approved by {_txt(f.get('approver'))}"
        )
    if tabla == "contracts":
        return f"Contract {f['contract_id']} with {_txt(f.get('vendor_rfc'))} for {pesos(f.get('value'))} from {_txt(f.get('start_date'))}"
    if tabla == "ledger":
        monto = max(_num(f.get("debit")) or 0, _num(f.get("credit")) or 0)
        return (
            f"Ledger entry {f['entry_id']} dated {_txt(f.get('date'))} in account {_txt(f.get('account_code'))} "
            f"for {pesos(monto)}, approved by {_txt(f.get('approver'))}"
        )
    if tabla == "vendors":
        return (
            f"Vendor registration for {_txt(f.get('rfc'))} ({_txt(f.get('legal_name'))}) on "
            f"{_txt(f.get('registered_date'))} with CLABE {_txt(f.get('bank_clabe'))}"
        )
    if tabla == "efos_list":
        return f"SAT listed {_txt(f.get('rfc'))} on the EFOS list with status {_txt(f.get('status'))} on {_txt(f.get('publication_date'))}"
    if tabla == "employees":
        return f"Employee {_txt(f.get('emp_id'))} ({_txt(f.get('name'))}, {_txt(f.get('role'))}) with CLABE {_txt(f.get('bank_clabe'))}"
    raise ValueError(f"Table without a description: {tabla}")


def _fecha(tabla: str, fila: dict) -> str:
    columna = {
        "invoices": "issue_date",
        "bank_txns": "date",
        "purchase_orders": "date",
        "contracts": "start_date",
        "ledger": "date",
        "vendors": "registered_date",
        "efos_list": "publication_date",
        "employees": "hire_date",
    }[tabla]
    return _txt(fila.get(columna))


def build_exhibits(estate: Estate, citas: Citas) -> list[dict]:
    """
    Un exhibit por registro citado, con nota de una oración sobre lo que prueba
    esa fila. Las llaves con guion bajo son internas (monto, fecha, fila) y no
    se publican. Falla si un registro citado no existe en el estate.
    """
    exhibits = []
    for (tabla, rid), motivos in citas.items():
        fila = estate.registro(tabla, rid)
        if fila is None:
            raise ValueError(f"Registro citado {tabla}.{rid} no existe en el estate")
        nota = _describir(tabla, fila)
        if motivos:
            nota += ": " + "; ".join(motivos)
        exhibits.append(
            {
                "exhibit_id": None,
                "source_table": tabla,
                "record_id": str(fila[TABLE_PK[tabla]]),
                "note": nota + ".",
                "_monto": _num(fila.get(AMOUNT_COLUMN.get(tabla))),
                "_fecha": _fecha(tabla, fila),
                "_fila": fila,
            }
        )
    exhibits.sort(
        key=lambda e: (ORDEN_TABLAS.index(e["source_table"]), e["_fecha"], e["record_id"])
    )
    for i, ex in enumerate(exhibits, start=1):
        ex["exhibit_id"] = f"EX-{i:02d}"
    return exhibits


def publicar_exhibits(exhibits: list[dict]) -> list[dict]:
    return [{k: v for k, v in ex.items() if not k.startswith("_")} for ex in exhibits]


def assert_exhibits_exist(estate: Estate, exhibits: list[dict]) -> None:
    for ex in exhibits:
        pk = TABLE_PK[ex["source_table"]]
        # Tabla y columna salen de TABLE_PK (lista cerrada), por eso f-string.
        existe = estate.con.execute(
            f"SELECT 1 FROM {ex['source_table']} WHERE CAST({pk} AS VARCHAR) = ? LIMIT 1",
            [ex["record_id"]],
        ).fetchone()
        if not existe:
            raise ValueError(
                f"Exhibit {ex['exhibit_id']} cita {ex['source_table']}.{ex['record_id']}, no existe en el estate"
            )


# --- montos -----------------------------------------------------------------------


def montos_por_tabla(exhibits: list[dict]) -> dict[str, float]:
    totales: dict[str, float] = {}
    for ex in exhibits:
        if ex["source_table"] in AMOUNT_COLUMN:
            totales[ex["source_table"]] = totales.get(ex["source_table"], 0.0) + (
                ex["_monto"] or 0.0
            )
    return totales


def compute_peso_amount(esquema: str, exhibits: list[dict]) -> tuple[float, str] | None:
    """Total de la tabla preferida del esquema; nunca suma tablas entre sí."""
    totales = montos_por_tabla(exhibits)
    for tabla in PRIORIDAD_MONTO[esquema]:
        if totales.get(tabla, 0.0) > 0:
            return round(totales[tabla], 2), tabla
    return None


def self_check_peso_reconciliation(
    peso: float, exhibits: list[dict], tolerancia: float = TOLERANCIA_PESOS
) -> bool:
    """Misma regla que validate_format.py: coincide con el total de alguna tabla citada."""
    totales = [t for t in montos_por_tabla(exhibits).values()]
    if not totales:
        return False
    mejor = min(totales, key=lambda t: abs(peso - t))
    return abs(peso - mejor) <= tolerancia * max(mejor, 1)


# --- money trail ------------------------------------------------------------------


def _etiqueta_clabe(resolutor: Resolutor, clabe) -> str:
    ents = resolutor.clabe(clabe)
    return " / ".join(format_entity_id(e.canonico, e.tipo) for e in ents) or f"CLABE:{_txt(clabe)}"


def build_money_trail(resolutor: Resolutor, exhibits: list[dict]) -> list[dict]:
    """
    Pasos en orden cronológico, cada uno citando su exhibit. Usa los pagos
    bancarios; si el Finding no cita ninguno, usa las facturas (quién le cobra
    a quién) y, en su defecto, las órdenes de compra.
    """
    por_tabla = {
        t: [e for e in exhibits if e["source_table"] == t]
        for t in ("bank_txns", "invoices", "purchase_orders")
    }
    pasos = []
    if por_tabla["bank_txns"]:
        for ex in por_tabla["bank_txns"]:
            f = ex["_fila"]
            pasos.append(
                {
                    "from": _etiqueta_clabe(resolutor, f.get("from_clabe")),
                    "to": _etiqueta_clabe(resolutor, f.get("to_clabe")),
                    "amount": round(ex["_monto"] or 0.0, 2),
                    "date": ex["_fecha"],
                    "exhibit_id": ex["exhibit_id"],
                }
            )
    elif por_tabla["invoices"]:
        for ex in por_tabla["invoices"]:
            f = ex["_fila"]
            pasos.append(
                {
                    "from": format_entity_id(_txt(f.get("receiver_rfc")).upper(), "rfc"),
                    "to": format_entity_id(_txt(f.get("issuer_rfc")).upper(), "rfc"),
                    "amount": round(ex["_monto"] or 0.0, 2),
                    "date": ex["_fecha"],
                    "exhibit_id": ex["exhibit_id"],
                }
            )
    else:
        for ex in por_tabla["purchase_orders"]:
            f = ex["_fila"]
            pasos.append(
                {
                    "from": format_entity_id(resolutor.estate.empresa_rfc or "EMPRESA", "rfc"),
                    "to": format_entity_id(_txt(f.get("vendor_rfc")).upper(), "rfc"),
                    "amount": round(ex["_monto"] or 0.0, 2),
                    "date": ex["_fecha"],
                    "exhibit_id": ex["exhibit_id"],
                }
            )
    pasos.sort(key=lambda p: (p["date"], p["exhibit_id"]))
    return pasos
