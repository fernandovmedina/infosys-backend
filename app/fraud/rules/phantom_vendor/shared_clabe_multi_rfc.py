import duckdb
import pandas as pd


def rule_shared_clabe_multi_rfc(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """
    Detecta una misma CLABE registrada para varios proveedores con RFC
    distinto: indicio de red de empresas fachada que canalizan pagos a una
    sola cuenta.

    Una fila por CLABE. entity_id = bank_clabe compartida (NO es un RFC).
    evidence_id = primer RFC en orden alfabético; la lista completa va en
    rfcs_involucrados. fecha_deteccion = registered_date más reciente del
    grupo (cuando la CLABE ya estaba compartida). Sin monto natural: NULL.

    Tablas: vendors
    Autosuficiencia: presuntiva
    """
    query = """
        SELECT
            'SHARED_CLABE_MULTI_RFC'                                AS rule_id,
            'vendors'                                               AS source_table,
            TRIM(bank_clabe)                                        AS entity_id,
            MIN(UPPER(TRIM(rfc)))                                   AS evidence_id,
            MAX(registered_date)                                    AS fecha_deteccion,
            'alta'                                                  AS severidad,
            'presuntiva'                                            AS autosuficiencia,
            CAST(NULL AS DOUBLE)                                    AS monto,
            STRING_AGG(DISTINCT UPPER(TRIM(rfc)), ', ' ORDER BY UPPER(TRIM(rfc))) AS rfcs_involucrados,
            COUNT(DISTINCT UPPER(TRIM(rfc)))                        AS num_rfcs,
            STRING_AGG(DISTINCT legal_name, ' | ' ORDER BY legal_name) AS razones_sociales
        FROM vendors
        WHERE bank_clabe IS NOT NULL
          AND TRIM(bank_clabe) <> ''
          AND rfc IS NOT NULL
        GROUP BY TRIM(bank_clabe)
        HAVING COUNT(DISTINCT UPPER(TRIM(rfc))) > 1
    """
    return con.execute(query).df()
