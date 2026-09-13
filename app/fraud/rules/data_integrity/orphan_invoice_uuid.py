import duckdb
import pandas as pd


def rule_orphan_invoice_uuid(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """
    Detecta asientos contables que citan un invoice_uuid inexistente en
    invoices: registro sin CFDI que lo soporte (Art. 27 fr. III y 29 CFF,
    deducción sin comprobante).

    UUID comparado con UPPER(TRIM(...)) en ambos lados. entity_id = el
    invoice_uuid huérfano (no es un RFC). evidence_id = entry_id del asiento.
    monto = el mayor entre debit y credit del asiento.

    Tablas: ledger, invoices
    Autosuficiencia: autosuficiente
    """
    query = """
        SELECT
            'ORPHAN_INVOICE_UUID'                                   AS rule_id,
            'ledger'                                                AS source_table,
            TRIM(l.invoice_uuid)                                    AS entity_id,
            CAST(l.entry_id AS VARCHAR)                             AS evidence_id,
            l.date                                                  AS fecha_deteccion,
            'alta'                                                  AS severidad,
            'autosuficiente'                                        AS autosuficiencia,
            GREATEST(COALESCE(l.debit, 0), COALESCE(l.credit, 0))   AS monto,
            l.account_code                                          AS cuenta,
            l.account_name                                          AS nombre_cuenta,
            l.description                                           AS descripcion,
            l.approver                                              AS approver
        FROM ledger l
        LEFT JOIN invoices i
          ON UPPER(TRIM(l.invoice_uuid)) = UPPER(TRIM(i.uuid))
        WHERE l.invoice_uuid IS NOT NULL
          AND TRIM(l.invoice_uuid) <> ''
          AND i.uuid IS NULL
    """
    return con.execute(query).df()
