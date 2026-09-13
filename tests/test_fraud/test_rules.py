"""
Pruebas de reglas con datos sintéticos en memoria: contrato de salida de todas
las reglas registradas y un caso positivo y uno negativo por regla nueva o
modificada.
"""

from collections.abc import Callable

import pytest

from app.fraud.engine.runner import (
    COLUMNAS_CONTRATO,
    cargar_reglas,
    nombre_regla,
    validar_contrato,
)
from app.fraud.rules.kickback.approver_vendor_concentration import (
    rule_approver_vendor_concentration,
)
from app.fraud.rules.revenue_inflation.ar_aging_excessive import rule_ar_aging_excessive
from app.fraud.rules.revenue_inflation.inflate_and_cancel import rule_inflate_and_cancel
from app.fraud.rules.round_tripping.bank_txn_not_in_ledger import rule_bank_txn_not_in_ledger
from app.fraud.rules.threshold_splitting.contract_split_into_pos import (
    rule_contract_split_into_pos,
)
from app.fraud.rules.threshold_splitting.same_approver_split import rule_same_approver_split

EMPRESA_CLABE = "646180000000000001"


@pytest.mark.parametrize("fn", cargar_reglas(), ids=nombre_regla)
def test_contrato_con_tablas_vacias(con, fn):
    df = fn(con)
    assert list(df.columns[: len(COLUMNAS_CONTRATO)]) == COLUMNAS_CONTRATO
    assert df.empty


@pytest.mark.parametrize("fn", cargar_reglas(), ids=nombre_regla)
def test_contrato_con_escenario_real(con_1301, fn):
    df = fn(con_1301)
    assert validar_contrato(df) == []
    assert df["evidence_id"].notna().all()


# --- APPROVER_VENDOR_CONCENTRATION ------------------------------------------------


def _facturas_con_aprobadores(
    insertar: Callable[..., None], aprobador_de: Callable[[int, int], str]
) -> None:
    """10 proveedores x 6 facturas; Tesorería firma todas y aprobador_de(v, k) registra."""
    k = 0
    for v in range(10):
        for _ in range(6):
            k += 1
            uuid = f"U{k:03d}"
            insertar(
                "invoices",
                {
                    "uuid": uuid,
                    "issuer_rfc": f"VEN{v}",
                    "issue_date": "2026-01-01",
                    "total": 100.0,
                },
            )
            insertar(
                "ledger",
                {"entry_id": 2 * k, "invoice_uuid": uuid, "approver": "Tesoreria"},
                {"entry_id": 2 * k + 1, "invoice_uuid": uuid, "approver": aprobador_de(v, k)},
            )


def test_approver_concentration_detecta_aprobador_concentrado(con, insertar):
    _facturas_con_aprobadores(insertar, lambda v, k: "A" if v == 1 else "ABC"[k % 3])
    df = rule_approver_vendor_concentration(con)
    assert list(zip(df["entity_id"], df["vendor_rfc"], strict=True)) == [("A", "VEN1")]


def test_approver_concentration_ignora_a_quien_firma_todo(con, insertar):
    _facturas_con_aprobadores(insertar, lambda v, k: "ABC"[k % 3])
    df = rule_approver_vendor_concentration(con)
    assert df.empty


# --- BANK_TXN_NOT_IN_LEDGER --------------------------------------------------------


def _pagos_normales(insertar: Callable[..., None]) -> None:
    for i in range(1, 6):
        insertar(
            "bank_txns",
            {
                "txn_id": f"B{i}",
                "date": "2026-02-01",
                "from_clabe": EMPRESA_CLABE,
                "to_clabe": f"64618000000000010{i}",
                "amount": 1000.0 * i,
            },
        )
        insertar(
            "ledger",
            {
                "entry_id": i,
                "date": "2026-02-01",
                "account_code": "1020",
                "credit": 1000.0 * i,
                "debit": 0.0,
            },
        )


def test_bank_txn_not_in_ledger_detecta_retorno_sin_asiento(con, insertar):
    _pagos_normales(insertar)
    insertar(
        "bank_txns",
        {
            "txn_id": "RET",
            "date": "2026-02-10",
            "from_clabe": "646180055500000009",
            "to_clabe": EMPRESA_CLABE,
            "amount": 4900.0,
        },
    )
    df = rule_bank_txn_not_in_ledger(con)
    assert df["evidence_id"].tolist() == ["RET"]
    assert df.loc[0, "direccion"] == "entrada"
    assert df.loc[0, "entity_id"] == "646180055500000009"


def test_bank_txn_not_in_ledger_acepta_reembolso_contabilizado(con, insertar):
    _pagos_normales(insertar)
    insertar(
        "bank_txns",
        {
            "txn_id": "RET",
            "date": "2026-02-10",
            "from_clabe": "646180000000000101",
            "to_clabe": EMPRESA_CLABE,
            "amount": 1000.0,
        },
    )
    insertar(
        "ledger",
        {
            "entry_id": 99,
            "date": "2026-02-11",
            "account_code": "1020",
            "debit": 1000.0,
            "credit": 0.0,
        },
    )
    df = rule_bank_txn_not_in_ledger(con)
    assert df.empty


# --- SAME_APPROVER_SPLIT y CONTRACT_SPLIT_INTO_POS --------------------------------


def _ordenes_seguidas(
    insertar: Callable[..., None], rfc: str = "VENX", aprobador: str = "Ana"
) -> None:
    for i, (fecha, monto) in enumerate(
        [("2026-02-10", 48000.0), ("2026-02-11", 48500.0), ("2026-02-12", 49000.0)]
    ):
        insertar(
            "purchase_orders",
            {
                "po_id": f"PO-{i}",
                "vendor_rfc": rfc,
                "date": fecha,
                "amount": monto,
                "requester": aprobador,
                "approver": aprobador,
            },
        )


def test_same_approver_split_una_fila_por_rafaga(con, insertar):
    _ordenes_seguidas(insertar)
    df = rule_same_approver_split(con)
    assert len(df) == 1
    assert df.loc[0, "evidence_id"] == "PO-0"
    assert df.loc[0, "num_ordenes_en_ventana"] == 3
    assert df.loc[0, "monto"] == pytest.approx(145500.0)


def test_same_approver_split_ignora_aprobadores_distintos(con, insertar):
    _ordenes_seguidas(insertar)
    con.execute("UPDATE purchase_orders SET approver = 'Otro' WHERE po_id = 'PO-1'")
    df = rule_same_approver_split(con)
    assert df.empty


def test_contract_split_detecta_contrato_partido(con, insertar):
    _ordenes_seguidas(insertar)
    insertar(
        "contracts",
        {
            "contract_id": "CTR-1",
            "vendor_rfc": "VENX",
            "start_date": "2026-02-10",
            "value": 145500.0,
        },
    )
    df = rule_contract_split_into_pos(con)
    assert df["evidence_id"].tolist() == ["CTR-1"]
    assert df.loc[0, "evidence_ids_relacionados"] == "PO-0, PO-1, PO-2"


def test_contract_split_ignora_contratos_por_orden(con, insertar):
    _ordenes_seguidas(insertar)
    for i, monto in enumerate([48000.0, 48500.0, 49000.0]):
        insertar(
            "contracts",
            {
                "contract_id": f"CTR-{i}",
                "vendor_rfc": "VENX",
                "start_date": "2026-02-10",
                "value": monto,
            },
        )
    df = rule_contract_split_into_pos(con)
    assert df.empty


# --- INFLATE_AND_CANCEL y AR_AGING_EXCESSIVE --------------------------------------


def _venta(
    insertar: Callable[..., None],
    uuid: str,
    fecha: str,
    revertida: bool = False,
    cobrada: bool = False,
    status: str = "cancelado",
    base: int = 100,
) -> None:
    insertar(
        "invoices",
        {
            "uuid": uuid,
            "issuer_rfc": "EMPRESA",
            "receiver_rfc": "CLIENTE",
            "issue_date": fecha,
            "subtotal": 1000.0,
            "iva": 160.0,
            "total": 1160.0,
            "status": status,
        },
    )
    renglones = [
        ("1050", "Cuentas por cobrar", 1160.0, 0.0),
        ("4000", "Ingresos por servicios", 0.0, 1000.0),
        ("2080", "IVA trasladado", 0.0, 160.0),
    ]
    if revertida:
        renglones += [(c, n, cr, db) for c, n, db, cr in renglones]
    if cobrada:
        renglones += [
            ("1050", "Cuentas por cobrar", 0.0, 1160.0),
            ("1020", "Bancos", 1160.0, 0.0),
        ]
    for i, (codigo, nombre, cargo, abono) in enumerate(renglones):
        insertar(
            "ledger",
            {
                "entry_id": base + i,
                "date": fecha,
                "account_code": codigo,
                "account_name": nombre,
                "debit": cargo,
                "credit": abono,
                "invoice_uuid": uuid,
            },
        )


def test_inflate_and_cancel_detecta_cancelacion_sin_reversion(con, insertar):
    _venta(insertar, "INV-1", "2026-02-01")
    df = rule_inflate_and_cancel(con)
    assert df["evidence_id"].tolist() == ["INV-1"]
    assert df.loc[0, "receiver_rfc"] == "CLIENTE"


def test_inflate_and_cancel_ignora_cancelacion_revertida(con, insertar):
    _venta(insertar, "INV-1", "2026-02-01", revertida=True)
    df = rule_inflate_and_cancel(con)
    assert df.empty


def test_ar_aging_detecta_cuenta_por_cobrar_vieja(con, insertar):
    _venta(insertar, "INV-1", "2026-01-01", status="vigente")
    _venta(insertar, "INV-2", "2026-06-30", status="vigente", cobrada=True, base=200)
    df = rule_ar_aging_excessive(con)
    assert df["invoice_uuid"].tolist() == ["INV-1"]
    assert df.loc[0, "dias_abierta"] == 180


def test_ar_aging_ignora_cuenta_cobrada(con, insertar):
    _venta(insertar, "INV-1", "2026-01-01", status="vigente", cobrada=True)
    _venta(insertar, "INV-2", "2026-06-30", status="vigente", cobrada=True, base=200)
    df = rule_ar_aging_excessive(con)
    assert df.empty
