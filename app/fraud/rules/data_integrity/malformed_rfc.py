import duckdb
import pandas as pd


def rule_malformed_rfc(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """
    Detecta RFC con formato inválido: longitud distinta de 12 (moral) o 13
    (física) caracteres, o caracteres fuera de [A-Z0-9Ñ&] (Art. 27 CFF, RFC).
    Ñ y & se aceptan porque el SAT los usa en RFC reales.

    Valida el valor tras UPPER(TRIM(...)), igual que los cruces del resto de
    reglas. Una sola función con UNION ALL sobre vendors.rfc,
    invoices.issuer_rfc, invoices.receiver_rfc y efos_list.rfc; source_table y
    columna_origen indican el origen real. RFC vacío solo se reporta en
    invoices, donde el uuid permite rastrear la fila (en vendors y efos_list el
    RFC es la llave), con entity_id = 'SIN_RFC'. evidence_id = rfc original en vendors/efos_list, uuid
    en invoices. monto = total en invoices, NULL en las demás.

    Tablas: vendors, invoices, efos_list
    Autosuficiencia: autosuficiente
    """
    query = """
        WITH rfcs AS (
            SELECT 'vendors' AS source_table, 'rfc' AS columna_origen,
                   rfc AS rfc_original, rfc AS evidence_id,
                   registered_date AS fecha, CAST(NULL AS DOUBLE) AS monto
            FROM vendors
            WHERE rfc IS NOT NULL

            UNION ALL

            SELECT 'invoices', 'issuer_rfc', issuer_rfc, uuid, issue_date, total
            FROM invoices

            UNION ALL

            SELECT 'invoices', 'receiver_rfc', receiver_rfc, uuid, issue_date, total
            FROM invoices

            UNION ALL

            SELECT 'efos_list', 'rfc', rfc, rfc, publication_date, CAST(NULL AS DOUBLE)
            FROM efos_list
            WHERE rfc IS NOT NULL
        ),
        validados AS (
            SELECT
                *,
                COALESCE(NULLIF(UPPER(TRIM(rfc_original)), ''), 'SIN_RFC') AS rfc_normalizado,
                CASE
                    WHEN rfc_original IS NULL OR TRIM(rfc_original) = ''
                        THEN 'vacío'
                    WHEN LENGTH(TRIM(rfc_original)) NOT IN (12, 13)
                        THEN 'longitud ' || LENGTH(TRIM(rfc_original))
                    WHEN NOT REGEXP_FULL_MATCH(UPPER(TRIM(rfc_original)), '[A-Z0-9Ñ&]+')
                        THEN 'caracteres inválidos'
                END AS motivo
            FROM rfcs
        )
        SELECT
            'MALFORMED_RFC'           AS rule_id,
            source_table              AS source_table,
            rfc_normalizado           AS entity_id,
            evidence_id               AS evidence_id,
            fecha                     AS fecha_deteccion,
            'media'                   AS severidad,
            'autosuficiente'          AS autosuficiencia,
            monto                     AS monto,
            columna_origen            AS columna_origen,
            rfc_original              AS rfc_original,
            motivo                    AS motivo
        FROM validados
        WHERE motivo IS NOT NULL
    """
    return con.execute(query).df()
