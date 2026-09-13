import duckdb
import pandas as pd


def rule_outbound_to_suspect_entity(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """
    Detecta transferencias a la CLABE de un proveedor sospechoso: RFC en la
    lista EFOS del SAT (Art. 69-B CFF) o CLABE compartida por varios RFC.
    Es la salida de dinero que suele iniciar un esquema de round tripping.

    Una fila por (transacción, proveedor dueño de la CLABE). Severidad
    dinámica: 'alta' si el RFC es EFOS 'definitivo', 'media' en los demás
    casos. Los motivos se listan en motivo_sospecha.

    Tablas: bank_txns, vendors, efos_list
    Autosuficiencia: presuntiva
    """
    query = """
        WITH proveedores AS (
            SELECT
                UPPER(TRIM(rfc))    AS rfc,
                legal_name,
                TRIM(bank_clabe)    AS clabe
            FROM vendors
            WHERE rfc IS NOT NULL
              AND bank_clabe IS NOT NULL
              AND TRIM(bank_clabe) <> ''
        ),
        clabes_compartidas AS (
            SELECT
                clabe,
                COUNT(DISTINCT rfc) AS num_rfcs
            FROM proveedores
            GROUP BY clabe
            HAVING COUNT(DISTINCT rfc) > 1
        ),
        efos AS (
            SELECT
                UPPER(TRIM(rfc))    AS rfc,
                status,
                publication_date
            FROM efos_list
            WHERE rfc IS NOT NULL
        )
        SELECT
            'OUTBOUND_TO_SUSPECT_ENTITY'                          AS rule_id,
            'bank_txns'                                           AS source_table,
            p.rfc                                                 AS entity_id,
            b.txn_id                                              AS evidence_id,
            b.date                                                AS fecha_deteccion,
            CASE WHEN e.status = 'definitivo' THEN 'alta'
                 ELSE 'media' END                                 AS severidad,
            'presuntiva'                                          AS autosuficiencia,
            b.amount                                              AS monto,
            CONCAT_WS('; ',
                CASE WHEN e.rfc IS NOT NULL THEN 'EFOS ' || e.status END,
                CASE WHEN cc.clabe IS NOT NULL
                     THEN 'CLABE compartida por ' || cc.num_rfcs || ' RFC' END
            )                                                     AS motivo_sospecha,
            p.legal_name                                          AS razon_social,
            TRIM(b.to_clabe)                                      AS destino_clabe,
            TRIM(b.from_clabe)                                    AS origen_clabe,
            e.status                                              AS efos_status,
            e.publication_date                                    AS efos_publication_date,
            b.reference                                           AS referencia,
            b.channel                                             AS canal
        FROM bank_txns b
        JOIN proveedores p
          ON TRIM(b.to_clabe) = p.clabe
        LEFT JOIN efos e
          ON p.rfc = e.rfc
        LEFT JOIN clabes_compartidas cc
          ON p.clabe = cc.clabe
        WHERE e.rfc IS NOT NULL
           OR cc.clabe IS NOT NULL
    """
    return con.execute(query).df()
