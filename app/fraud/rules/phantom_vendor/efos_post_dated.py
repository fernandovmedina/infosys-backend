import duckdb
import pandas as pd


def rule_efos_post_dated(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """
    Detecta facturas emitidas por un RFC en lista EFOS 'definitivo' antes de
    su publicación: la operación ocurrió y el SAT la señaló después, por lo
    que el efecto fiscal debe revisarse retroactivamente (Art. 69-B CFF).

    Las fechas son TEXT ISO 8601; se usa TRY_CAST para que una fecha mal
    formada excluya la fila en lugar de lanzar excepción.

    Tablas: invoices, efos_list
    Autosuficiencia: presuntiva
    """
    query = """
        SELECT
            'EFOS_POST_DATED'          AS rule_id,
            'invoices'                 AS source_table,
            UPPER(TRIM(i.issuer_rfc))  AS entity_id,
            i.uuid                     AS evidence_id,
            i.issue_date               AS fecha_deteccion,
            'media'                    AS severidad,
            'presuntiva'               AS autosuficiencia,
            i.total                    AS monto,
            e.status                   AS efos_status,
            e.publication_date         AS efos_publication_date,
            DATE_DIFF(
                'day',
                TRY_CAST(i.issue_date AS DATE),
                TRY_CAST(e.publication_date AS DATE)
            )                          AS dias_publicacion_posterior
        FROM invoices i
        JOIN efos_list e
          ON UPPER(TRIM(i.issuer_rfc)) = UPPER(TRIM(e.rfc))
        WHERE e.status = 'definitivo'
          AND TRY_CAST(e.publication_date AS DATE) > TRY_CAST(i.issue_date AS DATE)
    """
    return con.execute(query).df()
