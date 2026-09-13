import duckdb
import pandas as pd


def rule_ar_aging_excessive(
    con: duckdb.DuckDBPyConnection,
    dias_umbral: int = 90,
    tolerancia_monto: float = 0.01,
) -> pd.DataFrame:
    """
    Detecta cuentas por cobrar de una factura que siguen abiertas más de
    `dias_umbral` días: renglones del ledger en cuentas cuyo nombre contiene
    'cobrar' con saldo deudor pendiente (cargos - abonos) y sin póliza de cobro
    o reversión que lo cierre. Una venta que nunca se cobra es indicio de
    ingreso ficticio (Art. 28, fracción I CFF).

    Antigüedad medida contra la fecha de corte del estate (la fecha más
    reciente del ledger), no contra hoy, para que el resultado sea el mismo en
    cada corrida. Una fila por factura con saldo abierto.

    entity_id = receiver_rfc de la factura (el cliente que debe); evidence_id =
    entry_id del primer cargo a cuentas por cobrar de la factura. monto = saldo
    pendiente.

    Tablas: ledger, invoices
    Autosuficiencia: presuntiva
    """
    query = """
        WITH corte AS (
            SELECT MAX(TRY_CAST(date AS DATE)) AS fecha_corte
            FROM ledger
        ),
        cxc AS (
            SELECT
                UPPER(TRIM(invoice_uuid))                                       AS uuid,
                ARG_MIN(entry_id, (TRY_CAST(date AS DATE), entry_id))
                    FILTER (WHERE CAST(debit AS DOUBLE) > 0)                    AS primer_cargo,
                MIN(TRY_CAST(date AS DATE))                                     AS fecha_registro,
                SUM(CAST(debit AS DOUBLE)) - SUM(CAST(credit AS DOUBLE))        AS saldo
            FROM ledger
            WHERE account_name ILIKE '%cobrar%' OR account_name ILIKE '%receivable%'
              AND invoice_uuid IS NOT NULL
              AND TRIM(invoice_uuid) <> ''
              AND TRY_CAST(date AS DATE) IS NOT NULL
            GROUP BY UPPER(TRIM(invoice_uuid))
        )
        SELECT
            'AR_AGING_EXCESSIVE'                                AS rule_id,
            'ledger'                                            AS source_table,
            UPPER(TRIM(i.receiver_rfc))                         AS entity_id,
            c.primer_cargo                                      AS evidence_id,
            CAST(c.fecha_registro AS VARCHAR)                   AS fecha_deteccion,
            'media'                                             AS severidad,
            'presuntiva'                                        AS autosuficiencia,
            c.saldo                                             AS monto,
            UPPER(TRIM(i.issuer_rfc))                           AS issuer_rfc,
            i.uuid                                              AS invoice_uuid,
            i.status                                            AS status_factura,
            DATE_DIFF('day', c.fecha_registro, k.fecha_corte)   AS dias_abierta,
            CAST(k.fecha_corte AS VARCHAR)                      AS fecha_corte
        FROM cxc c
        JOIN invoices i
          ON UPPER(TRIM(i.uuid)) = c.uuid
        CROSS JOIN corte k
        WHERE c.saldo > $tolerancia_monto
          AND c.primer_cargo IS NOT NULL
          AND DATE_DIFF('day', c.fecha_registro, k.fecha_corte) > $dias_umbral
        ORDER BY c.fecha_registro, i.uuid
    """
    return con.execute(
        query, {"dias_umbral": dias_umbral, "tolerancia_monto": tolerancia_monto}
    ).df()
