import duckdb
import pandas as pd


def rule_no_segregation_of_duties(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """
    Detecta violación de segregación de funciones: la misma persona solicita
    y aprueba una orden de compra (requester = approver). Control interno
    básico de compras incumplido (COSO, segregación de funciones).

    Compara nombres con UPPER(TRIM(...)) para que diferencias de mayúsculas o
    espacios no oculten a la misma persona. entity_id = requester;
    evidence_id = po_id.

    Tablas: purchase_orders
    Autosuficiencia: autosuficiente
    """
    query = """
        SELECT
            'NO_SEGREGATION_OF_DUTIES'  AS rule_id,
            'purchase_orders'           AS source_table,
            TRIM(requester)             AS entity_id,
            po_id                       AS evidence_id,
            date                        AS fecha_deteccion,
            'alta'                      AS severidad,
            'autosuficiente'            AS autosuficiencia,
            CAST(amount AS DOUBLE)      AS monto,
            UPPER(TRIM(vendor_rfc))     AS vendor_rfc,
            approver                    AS approver,
            description                 AS descripcion
        FROM purchase_orders
        WHERE requester IS NOT NULL
          AND approver IS NOT NULL
          AND TRIM(requester) <> ''
          AND UPPER(TRIM(requester)) = UPPER(TRIM(approver))
    """
    return con.execute(query).df()
