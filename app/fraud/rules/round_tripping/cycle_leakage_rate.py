import duckdb
import pandas as pd


def rule_cycle_leakage_rate(
    con: duckdb.DuckDBPyConnection,
    max_nodos: int = 5,
    dias_ventana: int = 60,
    tolerancia_pct: float = 0.10,
    min_ciclos: int = 2,
    fuga_maxima: float = 0.10,
) -> pd.DataFrame:
    """
    Detecta contrapartes por las que el dinero circula en ciclos repetidos
    (al menos `min_ciclos`) y regresa casi íntegro al origen: la tasa de fuga
    promedio (1 - monto_retorno / monto_salida) es <= `fuga_maxima`. Una fuga
    pequeña y constante corresponde a la "comisión" del intermediario en
    esquemas de simulación de operaciones.

    Señal agregada por contraparte, no por transacción. Busca ciclos de 2 a
    `max_nodos` cuentas con la misma lógica temporal que BANK_CYCLE_NNODE
    (duplicada aquí a propósito: las reglas no dependen entre sí).
    entity_id = CLABE que recibe el primer movimiento de cada ciclo (no es un
    RFC). evidence_id = txn_id inicial del ciclo más antiguo; todos los
    txn_id iniciales van en evidence_ids_relacionados. monto = total que salió.

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
        ),
        ciclos AS (
            SELECT
                ruta[2]                   AS contraparte,
                clabe_inicial,
                txn_inicial,
                fecha_inicial,
                monto_inicial,
                monto_actual              AS monto_retorno,
                saltos
            FROM caminos
            WHERE clabe_actual = clabe_inicial
              AND saltos >= 2
        ),
        por_contraparte AS (
            SELECT
                contraparte,
                ARG_MIN(txn_inicial, (fecha_inicial, txn_inicial))          AS primer_txn,
                MIN(fecha_inicial)                                          AS primera_fecha,
                SUM(monto_inicial)                                          AS monto_salida_total,
                SUM(monto_retorno)                                          AS monto_retorno_total,
                AVG(1 - monto_retorno / monto_inicial)                      AS tasa_fuga_promedio,
                STDDEV(1 - monto_retorno / monto_inicial)                   AS tasa_fuga_stddev,
                COUNT(*)                                                    AS num_ciclos,
                STRING_AGG(DISTINCT clabe_inicial, ', ' ORDER BY clabe_inicial) AS clabes_origen,
                STRING_AGG(txn_inicial, ', ' ORDER BY fecha_inicial, txn_inicial) AS evidence_ids_relacionados
            FROM ciclos
            GROUP BY contraparte
        )
        SELECT
            'CYCLE_LEAKAGE_RATE'                  AS rule_id,
            'bank_txns'                           AS source_table,
            contraparte                           AS entity_id,
            primer_txn                            AS evidence_id,
            CAST(primera_fecha AS VARCHAR)        AS fecha_deteccion,
            'alta'                                AS severidad,
            'presuntiva'                          AS autosuficiencia,
            monto_salida_total                    AS monto,
            monto_retorno_total                   AS monto_retorno_total,
            tasa_fuga_promedio                    AS tasa_fuga_promedio,
            tasa_fuga_stddev                      AS tasa_fuga_stddev,
            num_ciclos                            AS num_ciclos,
            clabes_origen                         AS clabes_origen,
            evidence_ids_relacionados             AS evidence_ids_relacionados
        FROM por_contraparte
        WHERE num_ciclos >= $min_ciclos
          AND tasa_fuga_promedio <= $fuga_maxima
    """
    return con.execute(
        query,
        {
            "max_nodos": max_nodos,
            "dias_ventana": dias_ventana,
            "tolerancia_pct": tolerancia_pct,
            "min_ciclos": min_ciclos,
            "fuga_maxima": fuga_maxima,
        },
    ).df()
