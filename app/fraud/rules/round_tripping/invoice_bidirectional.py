import duckdb
import pandas as pd


def rule_invoice_bidirectional(
    con: duckdb.DuckDBPyConnection,
    dias_ventana: int = 90,
    tolerancia_pct: float = 0.20,
) -> pd.DataFrame:
    """
    Detecta facturación cruzada: A factura a B y B factura a A por un monto
    similar (±`tolerancia_pct` sobre total) dentro de `dias_ventana` días.
    Ingreso y gasto espejo con la misma contraparte simulan operaciones que
    se compensan (round tripping documental, Art. 69-B CFF).

    Una fila por par de facturas, anclada en la más antigua (fecha, uuid) para
    no reportar el par dos veces. entity_id = RFC emisor de esa factura;
    la contraparte y la factura espejo van en rfc_contraparte y uuid_espejo.

    Tablas: invoices
    Autosuficiencia: presuntiva
    """
    query = """
        WITH facturas AS (
            SELECT
                uuid,
                issue_date                    AS fecha_texto,
                TRY_CAST(issue_date AS DATE)  AS fecha,
                UPPER(TRIM(issuer_rfc))       AS emisor,
                UPPER(TRIM(receiver_rfc))     AS receptor,
                CAST(total AS DOUBLE)         AS total,
                status
            FROM invoices
            WHERE TRY_CAST(issue_date AS DATE) IS NOT NULL
              AND issuer_rfc IS NOT NULL
              AND receiver_rfc IS NOT NULL
              AND UPPER(TRIM(issuer_rfc)) <> UPPER(TRIM(receiver_rfc))
              AND total > 0
        )
        SELECT
            'INVOICE_BIDIRECTIONAL'                  AS rule_id,
            'invoices'                               AS source_table,
            a.emisor                                 AS entity_id,
            a.uuid                                   AS evidence_id,
            a.fecha_texto                            AS fecha_deteccion,
            'media'                                  AS severidad,
            'presuntiva'                             AS autosuficiencia,
            a.total                                  AS monto,
            a.receptor                               AS rfc_contraparte,
            b.uuid                                   AS uuid_espejo,
            b.fecha_texto                            AS fecha_espejo,
            b.total                                  AS monto_espejo,
            DATE_DIFF('day', a.fecha, b.fecha)       AS dias_entre_facturas,
            a.status                                 AS status_factura,
            b.status                                 AS status_espejo
        FROM facturas a
        JOIN facturas b
          ON b.emisor = a.receptor
         AND b.receptor = a.emisor
        WHERE b.fecha >= a.fecha
          -- Evita reportar el mismo par dos veces cuando ambas facturas son del mismo día
          AND (b.fecha > a.fecha OR b.uuid > a.uuid)
          AND DATE_DIFF('day', a.fecha, b.fecha) <= $dias_ventana
          AND b.total BETWEEN a.total * (1 - $tolerancia_pct)
                          AND a.total * (1 + $tolerancia_pct)
    """
    return con.execute(query, {"dias_ventana": dias_ventana, "tolerancia_pct": tolerancia_pct}).df()
