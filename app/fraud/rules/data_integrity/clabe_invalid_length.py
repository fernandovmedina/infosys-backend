import duckdb
import pandas as pd


def rule_clabe_invalid_length(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """
    Detecta CLABE interbancaria que no tiene exactamente 18 dígitos numéricos
    (estándar CLABE de Banxico), en vendors y employees. Una CLABE inválida
    rompe los cruces con bank_txns y puede ocultar pagos.

    Valida el valor tras TRIM, igual que los cruces del resto de reglas. CLABE
    vacía también se reporta (motivo 'vacía'). entity_id = RFC del proveedor
    o emp_id del empleado; evidence_id = llave de la fila (rfc / emp_id).
    Sin monto natural: NULL. No valida el dígito verificador.

    Tablas: vendors, employees
    Autosuficiencia: autosuficiente
    """
    query = """
        WITH clabes AS (
            SELECT 'vendors' AS source_table, UPPER(TRIM(rfc)) AS entity_id,
                   rfc AS evidence_id, registered_date AS fecha, bank_clabe
            FROM vendors
            WHERE rfc IS NOT NULL

            UNION ALL

            SELECT 'employees', emp_id, emp_id, hire_date, bank_clabe
            FROM employees
            WHERE emp_id IS NOT NULL
        ),
        validadas AS (
            SELECT
                *,
                CASE
                    WHEN bank_clabe IS NULL OR TRIM(bank_clabe) = ''
                        THEN 'vacía'
                    WHEN NOT REGEXP_FULL_MATCH(TRIM(bank_clabe), '[0-9]+')
                        THEN 'caracteres no numéricos'
                    WHEN LENGTH(TRIM(bank_clabe)) <> 18
                        THEN 'longitud ' || LENGTH(TRIM(bank_clabe))
                END AS motivo
            FROM clabes
        )
        SELECT
            'CLABE_INVALID_LENGTH'    AS rule_id,
            source_table              AS source_table,
            entity_id                 AS entity_id,
            evidence_id               AS evidence_id,
            fecha                     AS fecha_deteccion,
            'media'                   AS severidad,
            'autosuficiente'          AS autosuficiencia,
            CAST(NULL AS DOUBLE)      AS monto,
            bank_clabe                AS clabe_original,
            motivo                    AS motivo
        FROM validadas
        WHERE motivo IS NOT NULL
    """
    return con.execute(query).df()
