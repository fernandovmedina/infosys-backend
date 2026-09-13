import duckdb
import pandas as pd


def rule_approver_vendor_concentration(
    con: duckdb.DuckDBPyConnection,
    min_operaciones: int = 5,
    min_concentracion_relativa: float = 2.0,
) -> pd.DataFrame:
    """
    Detecta concentración de un mismo approver autorizando facturas de un
    mismo proveedor (más de `min_operaciones` facturas): indicio de relación
    indebida entre quien aprueba y el proveedor (kickback, falta de rotación
    en el control de autorización).

    Agrupa approver (ledger) + issuer_rfc (invoices, vía invoice_uuid). Cuenta
    facturas distintas y no asientos, porque una factura suele registrarse en
    varios renglones del ledger. Señal agregada: evidence_id = uuid de la
    primera factura del grupo (fecha, uuid) y la lista completa va en
    evidence_ids_relacionados. monto = total facturado en el grupo.

    Concentración relativa: el conteo absoluto no basta, porque quien firma
    todos los pagos (p. ej. tesorería) aparece en todas las facturas de todos
    los proveedores. Se exige además que la cuota del approver en las facturas
    del proveedor sea al menos `min_concentracion_relativa` veces su cuota en
    todas las facturas con approver:
        (facturas del proveedor que aprobó / facturas del proveedor)
        / (facturas que aprobó / facturas con approver)
    Quien aprueba el 100% de las facturas queda en 1.0 y nunca dispara: sin
    rotación no hay línea base contra la cual medir concentración.

    Tablas: ledger, invoices
    Autosuficiencia: presuntiva
    """
    query = """
        WITH operaciones AS (
            SELECT DISTINCT
                TRIM(l.approver)                AS approver,
                UPPER(TRIM(i.issuer_rfc))       AS vendor_rfc,
                i.uuid,
                i.issue_date,
                TRY_CAST(i.issue_date AS DATE)  AS fecha,
                CAST(i.total AS DOUBLE)         AS total
            FROM ledger l
            JOIN invoices i
              ON UPPER(TRIM(l.invoice_uuid)) = UPPER(TRIM(i.uuid))
            WHERE l.approver IS NOT NULL
              AND TRIM(l.approver) <> ''
              AND i.issuer_rfc IS NOT NULL
        ),
        total_facturas AS (
            SELECT COUNT(DISTINCT uuid) AS num_facturas
            FROM operaciones
        ),
        por_approver AS (
            SELECT approver, COUNT(DISTINCT uuid) AS num_facturas
            FROM operaciones
            GROUP BY approver
        ),
        por_proveedor AS (
            SELECT vendor_rfc, COUNT(DISTINCT uuid) AS num_facturas
            FROM operaciones
            GROUP BY vendor_rfc
        ),
        grupos AS (
            SELECT
                approver,
                vendor_rfc,
                ARG_MIN(uuid, (fecha, uuid))        AS primer_uuid,
                ARG_MIN(issue_date, (fecha, uuid))  AS primera_fecha,
                MAX(issue_date)                     AS ultima_fecha,
                COUNT(*)                            AS num_facturas,
                SUM(total)                          AS monto_total,
                STRING_AGG(uuid, ', ' ORDER BY fecha, uuid) AS evidence_ids_relacionados
            FROM operaciones
            GROUP BY approver, vendor_rfc
        ),
        concentracion AS (
            SELECT
                g.*,
                CAST(g.num_facturas AS DOUBLE) / pp.num_facturas  AS cuota_proveedor,
                CAST(pa.num_facturas AS DOUBLE) / t.num_facturas  AS cuota_global
            FROM grupos g
            JOIN por_approver pa  ON g.approver = pa.approver
            JOIN por_proveedor pp ON g.vendor_rfc = pp.vendor_rfc
            CROSS JOIN total_facturas t
        )
        SELECT
            'APPROVER_VENDOR_CONCENTRATION' AS rule_id,
            'invoices'                      AS source_table,
            approver                        AS entity_id,
            primer_uuid                     AS evidence_id,
            primera_fecha                   AS fecha_deteccion,
            'media'                         AS severidad,
            'presuntiva'                    AS autosuficiencia,
            monto_total                     AS monto,
            vendor_rfc                      AS vendor_rfc,
            num_facturas                    AS num_facturas,
            ultima_fecha                    AS ultima_fecha,
            evidence_ids_relacionados       AS evidence_ids_relacionados,
            ROUND(cuota_proveedor, 4)                AS cuota_proveedor,
            ROUND(cuota_global, 4)                   AS cuota_global,
            ROUND(cuota_proveedor / cuota_global, 2) AS concentracion_relativa
        FROM concentracion
        WHERE num_facturas > $min_operaciones
          AND cuota_proveedor / cuota_global >= $min_concentracion_relativa
    """
    return con.execute(
        query,
        {
            "min_operaciones": min_operaciones,
            "min_concentracion_relativa": min_concentracion_relativa,
        },
    ).df()
