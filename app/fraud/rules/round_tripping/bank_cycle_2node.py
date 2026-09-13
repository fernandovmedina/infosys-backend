import duckdb
import pandas as pd


def rule_bank_cycle_2node(
    con: duckdb.DuckDBPyConnection,
    dias_ventana: int = 30,
    tolerancia_pct: float = 0.10,
) -> pd.DataFrame:
    """
    Detecta ida y vuelta de dinero entre dos cuentas: A paga a B y, dentro de
    `dias_ventana` días, B devuelve a A un monto similar (±`tolerancia_pct`).
    Patrón de round tripping: el flujo simula una operación sin sustancia
    económica (materialidad, Art. 69-B CFF).

    Una fila por par (salida, retorno); si una salida tiene varios retornos
    compatibles, genera una fila por cada uno. entity_id = CLABE que recibe
    la salida y devuelve el dinero (no es un RFC). evidence_id = txn_id de la
    salida; el retorno va en txn_id_retorno.

    Tablas: bank_txns
    Autosuficiencia: presuntiva
    """
    query = """
        WITH txns AS (
            SELECT
                txn_id,
                date                      AS fecha_texto,
                TRY_CAST(date AS DATE)    AS fecha,
                TRIM(from_clabe)          AS origen,
                TRIM(to_clabe)            AS destino,
                CAST(amount AS DOUBLE)    AS amount
            FROM bank_txns
            WHERE TRY_CAST(date AS DATE) IS NOT NULL
              AND from_clabe IS NOT NULL
              AND to_clabe IS NOT NULL
              AND TRIM(from_clabe) <> TRIM(to_clabe)
              AND amount > 0
        )
        SELECT
            'BANK_CYCLE_2NODE'                         AS rule_id,
            'bank_txns'                                AS source_table,
            s.destino                                  AS entity_id,
            s.txn_id                                   AS evidence_id,
            s.fecha_texto                              AS fecha_deteccion,
            'alta'                                     AS severidad,
            'presuntiva'                               AS autosuficiencia,
            s.amount                                   AS monto,
            s.origen                                   AS clabe_origen,
            r.txn_id                                   AS txn_id_retorno,
            r.fecha_texto                              AS fecha_retorno,
            r.amount                                   AS monto_retorno,
            DATE_DIFF('day', s.fecha, r.fecha)         AS dias_hasta_retorno,
            1 - r.amount / s.amount                    AS tasa_fuga
        FROM txns s
        JOIN txns r
          ON r.origen = s.destino
         AND r.destino = s.origen
        WHERE r.fecha >= s.fecha
          -- Evita reportar el mismo par dos veces cuando ambos movimientos son del mismo día
          AND (r.fecha > s.fecha OR r.txn_id > s.txn_id)
          AND DATE_DIFF('day', s.fecha, r.fecha) <= $dias_ventana
          AND r.amount BETWEEN s.amount * (1 - $tolerancia_pct)
                           AND s.amount * (1 + $tolerancia_pct)
    """
    return con.execute(query, {"dias_ventana": dias_ventana, "tolerancia_pct": tolerancia_pct}).df()
