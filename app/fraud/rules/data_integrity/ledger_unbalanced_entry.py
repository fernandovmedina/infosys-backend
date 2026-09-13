import duckdb
import pandas as pd


def rule_ledger_unbalanced_entry(
    con: duckdb.DuckDBPyConnection, tolerancia: float = 0.01
) -> pd.DataFrame:
    """
    Detecta pólizas contables descuadradas: SUM(debit) <> SUM(credit) por más
    de `tolerancia` pesos (partida doble, NIF A-2 / Art. 28 CFF contabilidad).

    El ledger no tiene número de póliza, así que se agrupa por invoice_uuid +
    date (uuid normalizado con UPPER(TRIM(...))); los asientos sin factura o
    con uuid vacío del mismo día forman un solo grupo (entity_id = 'SIN_UUID'). Señal agregada: evidence_id = entry_id menor del
    grupo y la lista completa va en evidence_ids_relacionados.
    monto = diferencia absoluta. Montos convertidos a DOUBLE porque ledger usa
    REAL y la suma en float32 genera descuadres falsos por redondeo.

    Tablas: ledger
    Autosuficiencia: autosuficiente
    """
    query = """
        WITH polizas AS (
            SELECT
                NULLIF(UPPER(TRIM(invoice_uuid)), '')      AS invoice_uuid,
                date,
                SUM(COALESCE(CAST(debit AS DOUBLE), 0))    AS total_debe,
                SUM(COALESCE(CAST(credit AS DOUBLE), 0))   AS total_haber,
                MIN(entry_id)                              AS primer_entry_id,
                COUNT(*)                                   AS num_asientos,
                STRING_AGG(CAST(entry_id AS VARCHAR), ', ' ORDER BY entry_id) AS evidence_ids_relacionados,
                STRING_AGG(DISTINCT approver, ', ' ORDER BY approver)        AS approvers
            FROM ledger
            GROUP BY NULLIF(UPPER(TRIM(invoice_uuid)), ''), date
        )
        SELECT
            'LEDGER_UNBALANCED_ENTRY'                  AS rule_id,
            'ledger'                                   AS source_table,
            COALESCE(invoice_uuid, 'SIN_UUID')         AS entity_id,
            CAST(primer_entry_id AS VARCHAR)           AS evidence_id,
            date                                       AS fecha_deteccion,
            'alta'                                     AS severidad,
            'autosuficiente'                           AS autosuficiencia,
            ROUND(ABS(total_debe - total_haber), 2)    AS monto,
            ROUND(total_debe, 2)                       AS total_debe,
            ROUND(total_haber, 2)                      AS total_haber,
            ROUND(total_debe - total_haber, 2)         AS diferencia,
            num_asientos                               AS num_asientos,
            evidence_ids_relacionados                  AS evidence_ids_relacionados,
            approvers                                  AS approvers
        FROM polizas
        WHERE ABS(total_debe - total_haber) > ?
    """
    return con.execute(query, [tolerancia]).df()
