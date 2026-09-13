import duckdb
import pandas as pd


def rule_payment_to_employee_account(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """
    Detecta pagos bancarios cuyo destino (to_clabe) es la CLABE registrada de
    un empleado: posible kickback o proveedor simulado que cobra en la cuenta
    de un empleado (conflicto de interés).

    CLABE comparada tras TRIM; se ignoran CLABE vacías para no cruzar
    registros sin cuenta. entity_id = emp_id; evidence_id = txn_id.

    Tablas: bank_txns, employees
    Autosuficiencia: autosuficiente
    """
    query = """
        SELECT
            'PAYMENT_TO_EMPLOYEE_ACCOUNT' AS rule_id,
            'bank_txns'                   AS source_table,
            e.emp_id                      AS entity_id,
            b.txn_id                      AS evidence_id,
            b.date                        AS fecha_deteccion,
            'alta'                        AS severidad,
            'autosuficiente'              AS autosuficiencia,
            CAST(b.amount AS DOUBLE)      AS monto,
            e.name                        AS nombre_empleado,
            e.role                        AS puesto_empleado,
            TRIM(b.from_clabe)            AS origen_clabe,
            TRIM(b.to_clabe)              AS destino_clabe,
            b.reference                   AS referencia,
            b.channel                     AS canal
        FROM bank_txns b
        JOIN employees e
          ON TRIM(b.to_clabe) = TRIM(e.bank_clabe)
        WHERE e.bank_clabe IS NOT NULL
          AND TRIM(e.bank_clabe) <> ''
    """
    return con.execute(query).df()
