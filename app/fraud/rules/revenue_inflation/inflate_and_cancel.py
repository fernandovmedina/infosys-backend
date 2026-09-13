import duckdb
import pandas as pd


def rule_inflate_and_cancel(
    con: duckdb.DuckDBPyConnection,
    tolerancia_monto: float = 0.01,
) -> pd.DataFrame:
    """
    Detecta facturas canceladas cuyo registro contable sigue vigente: algún
    renglón del ledger ligado a la factura (invoice_uuid) deja saldo neto en
    su cuenta, es decir, la cancelación del CFDI no se revirtió en la
    contabilidad. El ingreso (o gasto) sigue inflado aunque la operación ya
    no existe. La contabilidad debe reflejar operaciones reales (Art. 28,
    fracción I CFF).

    Divergencia con la spec: `invoices` no tiene fecha de cancelación, así que
    no se distingue el cierre de ejercicio y la severidad queda en 'media'.
    En vez de reportar toda factura cancelada, se exige que la cancelación no
    esté revertida: una cancelación con su póliza de reversión deja todas las
    cuentas en cero y no dispara. Saldo por cuenta = suma de abonos - suma de
    cargos de los renglones de la factura, comparado con `tolerancia_monto`
    (pesos) por el redondeo de REAL.

    entity_id = issuer_rfc; evidence_id = uuid. monto = total de la factura.

    Tablas: invoices, ledger
    Autosuficiencia: presuntiva
    """
    query = """
        WITH saldos AS (
            SELECT
                UPPER(TRIM(invoice_uuid))                                   AS uuid,
                TRIM(account_code)                                          AS cuenta,
                MAX(account_name)                                           AS nombre_cuenta,
                SUM(CAST(credit AS DOUBLE)) - SUM(CAST(debit AS DOUBLE))    AS saldo_abono
            FROM ledger
            WHERE invoice_uuid IS NOT NULL
              AND TRIM(invoice_uuid) <> ''
            GROUP BY UPPER(TRIM(invoice_uuid)), TRIM(account_code)
        ),
        sin_revertir AS (
            SELECT
                uuid,
                COUNT(*)                                                    AS cuentas_con_saldo,
                STRING_AGG(cuenta || ' ' || nombre_cuenta || ': '
                           || CAST(ROUND(saldo_abono, 2) AS VARCHAR), '; '
                           ORDER BY cuenta)                                 AS saldos_pendientes
            FROM saldos
            WHERE ABS(saldo_abono) > ?
            GROUP BY uuid
        )
        SELECT
            'INFLATE_AND_CANCEL'            AS rule_id,
            'invoices'                      AS source_table,
            UPPER(TRIM(i.issuer_rfc))       AS entity_id,
            i.uuid                          AS evidence_id,
            i.issue_date                    AS fecha_deteccion,
            'media'                         AS severidad,
            'presuntiva'                    AS autosuficiencia,
            CAST(i.total AS DOUBLE)         AS monto,
            UPPER(TRIM(i.receiver_rfc))     AS receiver_rfc,
            i.concepto_text                 AS concepto,
            s.cuentas_con_saldo             AS cuentas_con_saldo,
            s.saldos_pendientes             AS saldos_pendientes
        FROM invoices i
        JOIN sin_revertir s
          ON UPPER(TRIM(i.uuid)) = s.uuid
        WHERE i.status = 'cancelado'
          AND i.issuer_rfc IS NOT NULL
        ORDER BY i.issue_date, i.uuid
    """
    return con.execute(query, [tolerancia_monto]).df()
