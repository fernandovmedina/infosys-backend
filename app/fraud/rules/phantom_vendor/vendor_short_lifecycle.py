import duckdb
import pandas as pd


def rule_vendor_short_lifecycle(
    con: duckdb.DuckDBPyConnection, dias_umbral: int = 30
) -> pd.DataFrame:
    """
    Detecta proveedores que facturan a pocos días de su alta (menos de
    `dias_umbral` días entre registered_date y su primera factura), patrón
    típico de empresa creada ex profeso para emitir comprobantes (EFOS/EDOS).

    Una fila por proveedor. evidence_id = uuid de la primera factura (desempate
    por uuid); monto = total de esa factura; monto_acumulado = total facturado
    por el proveedor. Un intervalo negativo (factura previa al alta) también
    dispara la señal.

    Tablas: vendors, invoices
    Autosuficiencia: presuntiva
    """
    query = """
        WITH facturas_proveedor AS (
            SELECT
                UPPER(TRIM(v.rfc))  AS rfc,
                v.legal_name,
                v.registered_date,
                i.uuid,
                i.issue_date,
                i.total,
                ROW_NUMBER() OVER (
                    PARTITION BY UPPER(TRIM(v.rfc))
                    ORDER BY TRY_CAST(i.issue_date AS DATE), i.uuid
                )                   AS orden_factura,
                SUM(i.total) OVER (PARTITION BY UPPER(TRIM(v.rfc))) AS monto_acumulado,
                COUNT(*) OVER (PARTITION BY UPPER(TRIM(v.rfc)))     AS num_facturas
            FROM vendors v
            JOIN invoices i
              ON UPPER(TRIM(i.issuer_rfc)) = UPPER(TRIM(v.rfc))
            WHERE TRY_CAST(v.registered_date AS DATE) IS NOT NULL
              AND TRY_CAST(i.issue_date AS DATE) IS NOT NULL
        )
        SELECT
            'VENDOR_SHORT_LIFECYCLE'   AS rule_id,
            'invoices'                 AS source_table,
            rfc                        AS entity_id,
            uuid                       AS evidence_id,
            issue_date                 AS fecha_deteccion,
            'media'                    AS severidad,
            'presuntiva'               AS autosuficiencia,
            total                      AS monto,
            DATE_DIFF(
                'day',
                CAST(registered_date AS DATE),
                CAST(issue_date AS DATE)
            )                          AS dias_hasta_primera_factura,
            registered_date            AS fecha_registro,
            legal_name                 AS razon_social,
            monto_acumulado            AS monto_acumulado,
            num_facturas               AS num_facturas
        FROM facturas_proveedor
        WHERE orden_factura = 1
          AND DATE_DIFF(
                'day',
                CAST(registered_date AS DATE),
                CAST(issue_date AS DATE)
              ) < ?
    """
    return con.execute(query, [dias_umbral]).df()
