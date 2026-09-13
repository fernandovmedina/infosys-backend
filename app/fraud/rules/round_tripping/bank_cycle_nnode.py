import duckdb
import pandas as pd


def rule_bank_cycle_nnode(
    con: duckdb.DuckDBPyConnection,
    max_nodos: int = 5,
    dias_ventana: int = 60,
    tolerancia_pct: float = 0.10,
) -> pd.DataFrame:
    """
    Detecta ciclos de dinero de 3 a `max_nodos` cuentas (A -> B -> C -> ... -> A)
    donde cada salto ocurre en orden cronológico, dentro de `dias_ventana` días
    desde el primer movimiento, y con monto similar al salto anterior
    (±`tolerancia_pct`). Round tripping con intermediarios para ocultar que el
    dinero regresa al origen. Los ciclos de 2 cuentas los cubre BANK_CYCLE_2NODE.

    Se implementa con CTE recursivo en DuckDB (búsqueda de caminos temporales)
    en lugar de networkx, para respetar el orden de fechas entre saltos. Cada
    ciclo se reporta una sola vez, anclado en su movimiento más antiguo
    (fecha, txn_id). entity_id = CLABE que recibe el primer movimiento (no es
    un RFC). evidence_id = txn_id inicial; el ciclo completo va en txns_ciclo.

    Tablas: bank_txns
    Autosuficiencia: presuntiva
    """
    query = """
        WITH RECURSIVE txns AS (
            SELECT
                txn_id,
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
        ),
        caminos AS (
            SELECT
                txn_id                    AS txn_inicial,
                origen                    AS clabe_inicial,
                destino                   AS clabe_actual,
                fecha                     AS fecha_inicial,
                fecha                     AS fecha_actual,
                amount                    AS monto_inicial,
                amount                    AS monto_actual,
                [origen, destino]         AS ruta,
                [txn_id]                  AS txns_ruta,
                1                         AS saltos
            FROM txns

            UNION ALL

            SELECT
                c.txn_inicial,
                c.clabe_inicial,
                t.destino,
                c.fecha_inicial,
                t.fecha,
                c.monto_inicial,
                t.amount,
                LIST_APPEND(c.ruta, t.destino),
                LIST_APPEND(c.txns_ruta, t.txn_id),
                c.saltos + 1
            FROM caminos c
            JOIN txns t
              ON t.origen = c.clabe_actual
            WHERE c.clabe_actual <> c.clabe_inicial          -- el camino ya cerró, no se extiende
              AND c.saltos < $max_nodos
              AND t.fecha >= c.fecha_actual
              -- Ancla el ciclo en su movimiento más antiguo para no repetirlo rotado
              AND (t.fecha > c.fecha_inicial OR t.txn_id > c.txn_inicial)
              AND DATE_DIFF('day', c.fecha_inicial, t.fecha) <= $dias_ventana
              AND t.amount BETWEEN c.monto_actual * (1 - $tolerancia_pct)
                               AND c.monto_actual * (1 + $tolerancia_pct)
              AND (t.destino = c.clabe_inicial OR NOT LIST_CONTAINS(c.ruta, t.destino))
        )
        SELECT
            'BANK_CYCLE_NNODE'                              AS rule_id,
            'bank_txns'                                     AS source_table,
            ruta[2]                                         AS entity_id,
            txn_inicial                                     AS evidence_id,
            CAST(fecha_inicial AS VARCHAR)                  AS fecha_deteccion,
            'alta'                                          AS severidad,
            'presuntiva'                                    AS autosuficiencia,
            monto_inicial                                   AS monto,
            clabe_inicial                                   AS clabe_origen,
            saltos                                          AS num_nodos,
            ARRAY_TO_STRING(ruta, ' -> ')                   AS ruta_clabes,
            ARRAY_TO_STRING(txns_ruta, ', ')                AS txns_ciclo,
            monto_actual                                    AS monto_retorno,
            DATE_DIFF('day', fecha_inicial, fecha_actual)   AS dias_ciclo,
            1 - monto_actual / monto_inicial                AS tasa_fuga
        FROM caminos
        WHERE clabe_actual = clabe_inicial
          AND saltos >= 3
    """
    return con.execute(
        query,
        {
            "max_nodos": max_nodos,
            "dias_ventana": dias_ventana,
            "tolerancia_pct": tolerancia_pct,
        },
    ).df()
