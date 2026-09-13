import duckdb
import pandas as pd


def rule_invoice_no_po_no_contract(
    con: duckdb.DuckDBPyConnection, monto_minimo: float = 50000.0
) -> pd.DataFrame:
    """
    Detecta facturas mayores a `monto_minimo` cuyo emisor no tiene ninguna
    orden de compra ni contrato: gasto sin soporte documental de la relación
    comercial (materialidad de la operación, Art. 69-B CFF).

    Usa LEFT JOIN + IS NULL contra los RFC distintos de cada tabla (no NOT IN,
    que falla ante NULLs, ni join directo, que multiplicaría filas).

    Tablas: invoices, purchase_orders, contracts
    Autosuficiencia: presuntiva
    """
    query = """
        WITH rfc_con_po AS (
            SELECT DISTINCT UPPER(TRIM(vendor_rfc)) AS rfc
            FROM purchase_orders
            WHERE vendor_rfc IS NOT NULL
        ),
        rfc_con_contrato AS (
            SELECT DISTINCT UPPER(TRIM(vendor_rfc)) AS rfc
            FROM contracts
            WHERE vendor_rfc IS NOT NULL
        )
        SELECT
            'INVOICE_NO_PO_NO_CONTRACT' AS rule_id,
            'invoices'                  AS source_table,
            UPPER(TRIM(i.issuer_rfc))   AS entity_id,
            i.uuid                      AS evidence_id,
            i.issue_date                AS fecha_deteccion,
            'media'                     AS severidad,
            'presuntiva'                AS autosuficiencia,
            i.total                     AS monto,
            i.concepto_text             AS concepto,
            i.status                    AS status_factura
        FROM invoices i
        LEFT JOIN rfc_con_po po
          ON UPPER(TRIM(i.issuer_rfc)) = po.rfc
        LEFT JOIN rfc_con_contrato c
          ON UPPER(TRIM(i.issuer_rfc)) = c.rfc
        WHERE po.rfc IS NULL
          AND c.rfc IS NULL
          AND i.issuer_rfc IS NOT NULL
          AND i.total > ?
    """
    return con.execute(query, [monto_minimo]).df()
