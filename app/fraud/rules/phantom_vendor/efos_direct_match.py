import duckdb
import pandas as pd


def rule_efos_direct_match(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """
    Detecta facturas donde el emisor (issuer_rfc) está en la lista EFOS
    del SAT con status 'definitivo' (Art. 69-B CFF).

    Tablas: invoices, efos_list
    Autosuficiencia: presuntiva
    """
    query = """
        SELECT
            'EFOS_DIRECT_MATCH'        AS rule_id,
            'invoices'                 AS source_table,
            UPPER(TRIM(i.issuer_rfc))  AS entity_id,
            i.uuid                     AS evidence_id,
            i.issue_date               AS fecha_deteccion,
            'alta'                     AS severidad,
            'presuntiva'               AS autosuficiencia,
            i.total                    AS monto,
            e.status                   AS efos_status,
            e.publication_date         AS efos_publication_date
        FROM invoices i
        JOIN efos_list e
          ON UPPER(TRIM(i.issuer_rfc)) = UPPER(TRIM(e.rfc))
        WHERE e.status = 'definitivo'
    """
    return con.execute(query).df()
