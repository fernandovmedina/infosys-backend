import duckdb
import pandas as pd


def rule_bank_txn_not_in_ledger(
    con: duckdb.DuckDBPyConnection,
    dias_tolerancia: int = 3,
    tolerancia_monto: float = 0.01,
) -> pd.DataFrame:
    """
    Detecta movimientos de la cuenta bancaria de la empresa que no tienen
    ningún asiento contable: entradas sin un cargo en el ledger por el mismo
    monto, o salidas sin un abono, dentro de ±`dias_tolerancia` días. Dinero
    que regresa a la empresa sin registrarse es la vuelta típica del round
    tripping; un reembolso legítimo sí se contabiliza. La contabilidad debe
    registrar todas las operaciones realizadas (Art. 28, fracción I CFF).

    La cuenta de la empresa es la CLABE que participa en más movimientos de
    bank_txns (la tabla es el estado de cuenta de la empresa auditada). Se
    compara contra cualquier cuenta contable del ledger, no solo bancos, para
    no depender del catálogo de cuentas: basta un renglón con el monto en el
    lado correcto. Montos comparados en DOUBLE con tolerancia `tolerancia_monto`
    (pesos) por el redondeo de REAL.

    entity_id = CLABE de la contraparte (no es un RFC). evidence_id = txn_id.

    Tablas: bank_txns, ledger
    Autosuficiencia: presuntiva
    """
    query = """
        WITH movimientos AS (
            SELECT
                txn_id,
                date                        AS fecha_texto,
                TRY_CAST(date AS DATE)      AS fecha,
                TRIM(from_clabe)            AS origen,
                TRIM(to_clabe)              AS destino,
                CAST(amount AS DOUBLE)      AS monto,
                reference,
                channel
            FROM bank_txns
            WHERE TRY_CAST(date AS DATE) IS NOT NULL
              AND from_clabe IS NOT NULL
              AND to_clabe IS NOT NULL
              AND amount > 0
        ),
        cuenta_empresa AS (
            SELECT clabe
            FROM (
                SELECT origen AS clabe FROM movimientos
                UNION ALL
                SELECT destino FROM movimientos
            )
            GROUP BY clabe
            ORDER BY COUNT(*) DESC, clabe
            LIMIT 1
        ),
        de_la_empresa AS (
            SELECT
                m.*,
                CASE WHEN m.destino = c.clabe THEN 'entrada' ELSE 'salida' END  AS direccion,
                c.clabe                                                           AS clabe_empresa
            FROM movimientos m
            JOIN cuenta_empresa c
              ON c.clabe IN (m.origen, m.destino)
            WHERE m.origen <> m.destino
        ),
        asientos AS (
            SELECT
                TRY_CAST(date AS DATE)          AS fecha,
                CAST(debit AS DOUBLE)           AS cargo,
                CAST(credit AS DOUBLE)          AS abono
            FROM ledger
            WHERE TRY_CAST(date AS DATE) IS NOT NULL
        )
        SELECT
            'BANK_TXN_NOT_IN_LEDGER'                                      AS rule_id,
            'bank_txns'                                                   AS source_table,
            CASE WHEN d.direccion = 'entrada' THEN d.origen
                 ELSE d.destino END                                       AS entity_id,
            d.txn_id                                                      AS evidence_id,
            d.fecha_texto                                                 AS fecha_deteccion,
            CASE WHEN d.direccion = 'entrada' THEN 'alta'
                 ELSE 'media' END                                         AS severidad,
            'presuntiva'                                                  AS autosuficiencia,
            d.monto                                                       AS monto,
            d.direccion                                                   AS direccion,
            d.clabe_empresa                                               AS clabe_empresa,
            d.origen                                                      AS origen_clabe,
            d.destino                                                     AS destino_clabe,
            d.reference                                                   AS referencia,
            d.channel                                                     AS canal
        FROM de_la_empresa d
        LEFT JOIN asientos a
          ON ABS(DATE_DIFF('day', a.fecha, d.fecha)) <= $dias_tolerancia
         AND ABS(CASE WHEN d.direccion = 'entrada' THEN a.cargo ELSE a.abono END - d.monto) <= $tolerancia_monto
        WHERE a.fecha IS NULL
        ORDER BY d.fecha, d.txn_id
    """
    return con.execute(
        query,
        {"dias_tolerancia": dias_tolerancia, "tolerancia_monto": tolerancia_monto},
    ).df()
