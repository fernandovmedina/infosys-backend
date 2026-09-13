import duckdb
import pandas as pd


def rule_price_outlier_by_category(
    con: duckdb.DuckDBPyConnection,
    desviaciones: float = 2.0,
    min_facturas_categoria: int = 3,
) -> pd.DataFrame:
    """
    Detecta facturas cuyo subtotal se desvía más de `desviaciones`
    desviaciones estándar de la media de su categoría de proveedor
    (vendors.category): sobreprecio que puede esconder un kickback.

    Media y desviación con funciones de ventana por categoría. Solo evalúa
    categorías con al menos `min_facturas_categoria` facturas y desviación
    mayor a cero, para no señalar por falta de datos. La desviación se mide en
    ambos sentidos; z_score indica si está por encima (positivo) o por debajo.

    Tablas: invoices, vendors
    Autosuficiencia: presuntiva
    """
    query = """
        WITH facturas AS (
            SELECT
                i.uuid,
                i.issue_date,
                UPPER(TRIM(i.issuer_rfc))           AS rfc,
                CAST(i.subtotal AS DOUBLE)          AS subtotal,
                i.concepto_text,
                v.category,
                AVG(CAST(i.subtotal AS DOUBLE))    OVER (PARTITION BY v.category) AS prom_categoria,
                STDDEV(CAST(i.subtotal AS DOUBLE)) OVER (PARTITION BY v.category) AS stddev_categoria,
                COUNT(*)                           OVER (PARTITION BY v.category) AS num_facturas_categoria
            FROM invoices i
            JOIN vendors v
              ON UPPER(TRIM(i.issuer_rfc)) = UPPER(TRIM(v.rfc))
            WHERE v.category IS NOT NULL
              AND i.subtotal > 0
        )
        SELECT
            'PRICE_OUTLIER_BY_CATEGORY'  AS rule_id,
            'invoices'                   AS source_table,
            rfc                          AS entity_id,
            uuid                         AS evidence_id,
            issue_date                   AS fecha_deteccion,
            'media'                      AS severidad,
            'presuntiva'                 AS autosuficiencia,
            subtotal                     AS monto,
            category                     AS categoria,
            concepto_text                AS concepto,
            prom_categoria               AS prom_categoria,
            stddev_categoria             AS stddev_categoria,
            num_facturas_categoria       AS num_facturas_categoria,
            (subtotal - prom_categoria) / stddev_categoria AS z_score
        FROM facturas
        WHERE stddev_categoria > 0
          AND num_facturas_categoria >= $min_facturas_categoria
          AND ABS(subtotal - prom_categoria) > $desviaciones * stddev_categoria
    """
    return con.execute(
        query,
        {"desviaciones": desviaciones, "min_facturas_categoria": min_facturas_categoria},
    ).df()
