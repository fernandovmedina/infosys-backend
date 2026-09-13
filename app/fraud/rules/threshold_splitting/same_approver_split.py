import duckdb
import pandas as pd


def rule_same_approver_split(
    con: duckdb.DuckDBPyConnection,
    dias_ventana: int = 7,
    umbral_monto: float = 50000.0,
) -> pd.DataFrame:
    """
    Detecta ráfagas de órdenes de compra al mismo proveedor dentro de
    `dias_ventana` días, todas autorizadas por el mismo approver, cuya suma
    supera `umbral_monto`: indicio de fraccionamiento de una compra para que
    cada orden quede bajo el límite de autorización y la apruebe una sola
    persona (evasión del control interno de montos).

    Una fila por ráfaga: la ventana arranca en una orden sin otra orden previa
    del mismo proveedor y approver en los `dias_ventana` días anteriores, así
    las sub-ventanas de la misma ráfaga no se repiten. entity_id = vendor_rfc;
    evidence_id = po_id que inicia la ventana; todas las órdenes van en
    evidence_ids_relacionados. monto = monto acumulado de la ventana.

    Tablas: purchase_orders
    Autosuficiencia: autosuficiente
    """
    # INTERVAL no admite placeholder en DuckDB: dias_ventana se castea a int y va
    # en f-string solo para construir la sintaxis del intervalo.
    intervalo = f"INTERVAL {int(dias_ventana)} DAY"
    query = f"""
        WITH ordenes AS (
            SELECT
                po_id,
                UPPER(TRIM(vendor_rfc))     AS vendor_rfc,
                date                        AS fecha_texto,
                TRY_CAST(date AS DATE)      AS fecha,
                CAST(amount AS DOUBLE)      AS monto,
                TRIM(approver)              AS approver,
                TRIM(requester)             AS requester
            FROM purchase_orders
            WHERE TRY_CAST(date AS DATE) IS NOT NULL
              AND vendor_rfc IS NOT NULL
              AND approver IS NOT NULL
              AND TRIM(approver) <> ''
        ),
        anclas AS (
            SELECT a.*
            FROM ordenes a
            LEFT JOIN ordenes previa
              ON previa.vendor_rfc = a.vendor_rfc
             AND previa.approver = a.approver
             AND previa.po_id <> a.po_id
             AND (previa.fecha < a.fecha OR (previa.fecha = a.fecha AND previa.po_id < a.po_id))
             AND previa.fecha >= a.fecha - {intervalo}
            WHERE previa.po_id IS NULL
        ),
        ventanas AS (
            SELECT
                a.po_id                                         AS po_inicial,
                a.vendor_rfc,
                a.approver,
                a.fecha_texto,
                COUNT(*)                                        AS num_ordenes,
                SUM(o.monto)                                    AS monto_acumulado,
                COUNT(DISTINCT o.approver)                      AS num_approvers,
                BOOL_AND(o.requester = o.approver)              AS mismo_solicitante,
                MAX(o.fecha_texto)                              AS ultima_fecha,
                STRING_AGG(o.po_id, ', ' ORDER BY o.fecha, o.po_id) AS evidence_ids_relacionados
            FROM anclas a
            JOIN ordenes o
              ON o.vendor_rfc = a.vendor_rfc
             AND o.fecha BETWEEN a.fecha AND a.fecha + {intervalo}
            GROUP BY a.po_id, a.vendor_rfc, a.approver, a.fecha_texto
        )
        SELECT
            'SAME_APPROVER_SPLIT'           AS rule_id,
            'purchase_orders'               AS source_table,
            vendor_rfc                      AS entity_id,
            po_inicial                      AS evidence_id,
            fecha_texto                     AS fecha_deteccion,
            'alta'                          AS severidad,
            'autosuficiente'                AS autosuficiencia,
            monto_acumulado                 AS monto,
            approver                        AS approver,
            num_ordenes                     AS num_ordenes_en_ventana,
            monto_acumulado                 AS monto_acumulado_ventana,
            mismo_solicitante               AS approver_es_solicitante,
            ultima_fecha                    AS ultima_fecha,
            evidence_ids_relacionados       AS evidence_ids_relacionados
        FROM ventanas
        WHERE num_ordenes >= 2
          AND num_approvers = 1
          AND monto_acumulado > ?
        ORDER BY fecha_texto, po_inicial
    """
    return con.execute(query, [umbral_monto]).df()
