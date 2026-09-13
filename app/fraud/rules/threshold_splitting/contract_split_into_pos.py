import duckdb
import pandas as pd


def rule_contract_split_into_pos(
    con: duckdb.DuckDBPyConnection,
    dias_ventana: int = 7,
    tolerancia_pct: float = 0.02,
) -> pd.DataFrame:
    """
    Detecta contratos cuyo valor coincide (±`tolerancia_pct`) con la suma de 2
    o más órdenes de compra del mismo proveedor emitidas en los primeros
    `dias_ventana` días del contrato, cada una por menos que el contrato: una
    sola obligación documentada que se pidió en pedazos. Es fraccionamiento
    para evadir el monto que exige autorización superior o conjunta (control
    interno de compras). Evidencia independiente de SAME_APPROVER_SPLIT: cruza
    contracts contra purchase_orders en vez de mirar solo las órdenes.

    Órdenes con contratos propios (una obligación por orden) no disparan,
    porque ninguna suma de varias coincide con un solo contrato.

    entity_id = vendor_rfc; evidence_id = contract_id. Las órdenes van en
    evidence_ids_relacionados y sus approvers en aprobadores. monto = valor
    del contrato.

    Tablas: contracts, purchase_orders
    Autosuficiencia: presuntiva
    """
    # INTERVAL no admite placeholder en DuckDB: dias_ventana se castea a int y va
    # en f-string solo para construir la sintaxis del intervalo.
    intervalo = f"INTERVAL {int(dias_ventana)} DAY"
    query = f"""
        WITH contratos AS (
            SELECT
                contract_id,
                UPPER(TRIM(vendor_rfc))         AS vendor_rfc,
                start_date,
                TRY_CAST(start_date AS DATE)    AS inicio,
                CAST(value AS DOUBLE)           AS valor,
                scope_text
            FROM contracts
            WHERE TRY_CAST(start_date AS DATE) IS NOT NULL
              AND vendor_rfc IS NOT NULL
              AND value > 0
        ),
        ordenes AS (
            SELECT
                po_id,
                UPPER(TRIM(vendor_rfc))     AS vendor_rfc,
                TRY_CAST(date AS DATE)      AS fecha,
                CAST(amount AS DOUBLE)      AS monto,
                TRIM(approver)              AS approver
            FROM purchase_orders
            WHERE TRY_CAST(date AS DATE) IS NOT NULL
              AND vendor_rfc IS NOT NULL
        ),
        cruce AS (
            SELECT
                c.contract_id,
                c.vendor_rfc,
                c.start_date,
                c.valor,
                c.scope_text,
                COUNT(*)                                            AS num_ordenes,
                SUM(o.monto)                                        AS suma_ordenes,
                STRING_AGG(o.po_id, ', ' ORDER BY o.fecha, o.po_id) AS evidence_ids_relacionados,
                STRING_AGG(DISTINCT o.approver, ', ')               AS aprobadores
            FROM contratos c
            JOIN ordenes o
              ON o.vendor_rfc = c.vendor_rfc
             AND o.fecha BETWEEN c.inicio AND c.inicio + {intervalo}
             AND o.monto < c.valor
            GROUP BY c.contract_id, c.vendor_rfc, c.start_date, c.valor, c.scope_text
        )
        SELECT
            'CONTRACT_SPLIT_INTO_POS'       AS rule_id,
            'contracts'                     AS source_table,
            vendor_rfc                      AS entity_id,
            contract_id                     AS evidence_id,
            start_date                      AS fecha_deteccion,
            'alta'                          AS severidad,
            'presuntiva'                    AS autosuficiencia,
            valor                           AS monto,
            num_ordenes                     AS num_ordenes,
            suma_ordenes                    AS suma_ordenes,
            evidence_ids_relacionados       AS evidence_ids_relacionados,
            aprobadores                     AS aprobadores,
            scope_text                      AS alcance_contrato
        FROM cruce
        WHERE num_ordenes >= 2
          AND ABS(suma_ordenes - valor) <= ? * valor
        ORDER BY start_date, contract_id
    """
    return con.execute(query, [tolerancia_pct]).df()
