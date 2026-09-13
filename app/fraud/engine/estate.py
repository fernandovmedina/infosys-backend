"""
Consultas de solo lectura al estate que usa el investigador. Cada consulta se
registra en una bitácora por nombre, para reportar en `tool_calls_made` qué se
revisó antes de acusar o descartar una pista.
"""

from contextlib import contextmanager

import duckdb

from .catalogo import TABLE_PK


class Estate:
    def __init__(self, con: duckdb.DuckDBPyConnection):
        self.con = con
        self._bitacora: list[str] | None = None
        self.empresa_rfc = self._empresa_rfc()
        self.empresa_clabes = self._empresa_clabes()

    # --- bitácora -----------------------------------------------------------

    @contextmanager
    def registrar(self):
        """Durante el bloque, acumula los nombres de consulta usados (sin repetir)."""
        anterior, self._bitacora = self._bitacora, []
        try:
            yield self._bitacora
        finally:
            self._bitacora = anterior

    def _anotar(self, nombre: str) -> None:
        if self._bitacora is not None and nombre not in self._bitacora:
            self._bitacora.append(nombre)

    def _filas(self, query: str, params: list | dict) -> list[dict]:
        cur = self.con.execute(query, params)
        columnas = [d[0] for d in cur.description]
        return [dict(zip(columnas, fila)) for fila in cur.fetchall()]

    # --- empresa auditada ---------------------------------------------------

    def _empresa_rfc(self) -> str | None:
        """RFC que aparece en más facturas, como emisor o receptor."""
        fila = self.con.execute(
            """
            SELECT rfc FROM (
                SELECT UPPER(TRIM(issuer_rfc)) AS rfc FROM invoices
                UNION ALL
                SELECT UPPER(TRIM(receiver_rfc)) FROM invoices
            )
            WHERE rfc IS NOT NULL AND rfc <> ''
            GROUP BY rfc
            ORDER BY COUNT(*) DESC, rfc
            LIMIT 1
            """
        ).fetchone()
        return fila[0] if fila else None

    def _empresa_clabes(self) -> set[str]:
        """
        CLABE de origen desde la que se paga a proveedores y empleados del
        catálogo, más las CLABE de la propia empresa si está en vendors.
        """
        filas = self.con.execute(
            """
            WITH catalogo AS (
                SELECT TRIM(bank_clabe) AS clabe FROM vendors WHERE bank_clabe IS NOT NULL
                UNION
                SELECT TRIM(bank_clabe) FROM employees WHERE bank_clabe IS NOT NULL
            ),
            origenes AS (
                SELECT TRIM(b.from_clabe) AS clabe, COUNT(*) AS n
                FROM bank_txns b
                JOIN catalogo c ON TRIM(b.to_clabe) = c.clabe
                WHERE b.from_clabe IS NOT NULL
                GROUP BY TRIM(b.from_clabe)
            )
            SELECT clabe FROM origenes
            WHERE clabe NOT IN (SELECT clabe FROM catalogo)
            ORDER BY n DESC, clabe
            LIMIT 1
            """
        ).fetchall()
        clabes = {f[0] for f in filas}
        if self.empresa_rfc:
            clabes |= {
                f[0]
                for f in self.con.execute(
                    "SELECT TRIM(bank_clabe) FROM vendors "
                    "WHERE UPPER(TRIM(rfc)) = ? AND bank_clabe IS NOT NULL",
                    [self.empresa_rfc],
                ).fetchall()
            }
        return clabes

    def periodo(self) -> tuple[str | None, str | None]:
        return self.con.execute(
            """
            SELECT CAST(MIN(f) AS VARCHAR), CAST(MAX(f) AS VARCHAR) FROM (
                SELECT TRY_CAST(issue_date AS DATE) AS f FROM invoices
                UNION ALL SELECT TRY_CAST(date AS DATE) FROM ledger
                UNION ALL SELECT TRY_CAST(date AS DATE) FROM bank_txns
            )
            """
        ).fetchone()

    # --- catálogos ----------------------------------------------------------

    def vendors_por_rfc(self, rfc: str) -> list[dict]:
        self._anotar("consultar_vendors")
        return self._filas(
            "SELECT rfc, legal_name, registered_date, bank_clabe, category FROM vendors "
            "WHERE UPPER(TRIM(rfc)) = ? ORDER BY rfc",
            [rfc],
        )

    def vendors_por_clabe(self, clabe: str) -> list[dict]:
        self._anotar("consultar_vendors")
        return self._filas(
            "SELECT rfc, legal_name FROM vendors WHERE TRIM(bank_clabe) = ? ORDER BY rfc",
            [clabe],
        )

    def employees_por_clabe(self, clabe: str) -> list[dict]:
        self._anotar("consultar_employees")
        return self._filas(
            "SELECT emp_id, name, role FROM employees WHERE TRIM(bank_clabe) = ? ORDER BY emp_id",
            [clabe],
        )

    def employees_por_nombre(self, nombre: str) -> list[dict]:
        self._anotar("consultar_employees")
        return self._filas(
            "SELECT emp_id, name, role FROM employees "
            "WHERE UPPER(TRIM(name)) = UPPER(TRIM(?)) OR TRIM(emp_id) = TRIM(?) ORDER BY emp_id",
            [nombre, nombre],
        )

    def employee_por_id(self, emp_id: str) -> list[dict]:
        self._anotar("consultar_employees")
        return self._filas(
            "SELECT emp_id, name, role, bank_clabe FROM employees WHERE TRIM(emp_id) = ?",
            [emp_id],
        )

    def efos_por_rfc(self, rfc: str) -> list[dict]:
        self._anotar("consultar_efos_list")
        return self._filas(
            "SELECT rfc, status, publication_date FROM efos_list "
            "WHERE UPPER(TRIM(rfc)) = ? ORDER BY rfc",
            [rfc],
        )

    def ordenes_por_rfc(self, rfc: str) -> list[dict]:
        self._anotar("consultar_purchase_orders")
        return self._filas(
            "SELECT po_id, amount, date FROM purchase_orders "
            "WHERE UPPER(TRIM(vendor_rfc)) = ? ORDER BY date, po_id",
            [rfc],
        )

    def contratos_por_rfc(self, rfc: str) -> list[dict]:
        self._anotar("consultar_contracts")
        return self._filas(
            "SELECT contract_id, value, start_date FROM contracts "
            "WHERE UPPER(TRIM(vendor_rfc)) = ? ORDER BY start_date, contract_id",
            [rfc],
        )

    def facturas_emitidas_por(self, rfc: str) -> list[dict]:
        self._anotar("consultar_invoices")
        return self._filas(
            "SELECT uuid FROM invoices WHERE UPPER(TRIM(issuer_rfc)) = ? ORDER BY issue_date, uuid",
            [rfc],
        )

    def autorizaciones_de(self, nombre: str, limite: int) -> list[dict]:
        """Órdenes de compra y asientos que la persona solicitó o aprobó, más recientes primero."""
        self._anotar("consultar_autorizaciones")
        return self._filas(
            """
            SELECT tabla, id FROM (
                SELECT 'purchase_orders' AS tabla, po_id AS id, date AS fecha FROM purchase_orders
                WHERE UPPER(TRIM(approver)) = UPPER(TRIM($n)) OR UPPER(TRIM(requester)) = UPPER(TRIM($n))
                UNION ALL
                SELECT 'ledger', CAST(entry_id AS VARCHAR), date FROM ledger
                WHERE UPPER(TRIM(approver)) = UPPER(TRIM($n))
            )
            ORDER BY fecha DESC, tabla, id
            LIMIT $limite
            """,
            {"n": nombre, "limite": limite},
        )

    def pagos_a_clabe(self, clabe: str) -> list[dict]:
        self._anotar("consultar_bank_txns")
        return self._filas(
            "SELECT txn_id FROM bank_txns WHERE TRIM(to_clabe) = ? ORDER BY date, txn_id",
            [clabe],
        )

    def facturas_pagadas_por(self, txn_id: str) -> list[dict]:
        """
        Facturas que liquida una transferencia: emitidas por el proveedor dueño de
        la CLABE destino y con un abono en el ledger por el mismo monto ese día.
        """
        self._anotar("consultar_ledger")
        return self._filas(
            """
            SELECT DISTINCT i.uuid
            FROM bank_txns b
            JOIN vendors v
              ON TRIM(v.bank_clabe) = TRIM(b.to_clabe)
            JOIN invoices i
              ON UPPER(TRIM(i.issuer_rfc)) = UPPER(TRIM(v.rfc))
            JOIN ledger l
              ON TRIM(l.invoice_uuid) = TRIM(i.uuid)
             AND TRY_CAST(l.date AS DATE) = TRY_CAST(b.date AS DATE)
             AND ABS(CAST(l.credit AS DOUBLE) - CAST(b.amount AS DOUBLE)) <= 0.01
            WHERE b.txn_id = ?
            ORDER BY i.uuid
            """,
            [txn_id],
        )

    def cancelaciones_revertidas(self, rfc: str) -> list[dict]:
        """
        Facturas canceladas emitidas por `rfc` cuya contabilidad quedó en cero en
        todas las cuentas (la cancelación se revirtió). Es el caso limpio de
        INFLATE_AND_CANCEL, que se reporta como pista descartada.
        """
        self._anotar("consultar_ledger")
        return self._filas(
            """
            WITH saldos AS (
                SELECT UPPER(TRIM(invoice_uuid)) AS uuid,
                       SUM(CAST(credit AS DOUBLE)) - SUM(CAST(debit AS DOUBLE)) AS saldo,
                       COUNT(*) AS renglones
                FROM ledger
                WHERE invoice_uuid IS NOT NULL AND TRIM(invoice_uuid) <> ''
                GROUP BY UPPER(TRIM(invoice_uuid)), TRIM(account_code)
            )
            SELECT i.uuid, i.issue_date, CAST(i.total AS DOUBLE) AS total, SUM(s.renglones) AS renglones
            FROM invoices i
            JOIN saldos s ON s.uuid = UPPER(TRIM(i.uuid))
            WHERE i.status = 'cancelado'
              AND UPPER(TRIM(i.issuer_rfc)) = ?
            GROUP BY i.uuid, i.issue_date, i.total
            HAVING MAX(ABS(s.saldo)) <= 0.01
            ORDER BY i.issue_date, i.uuid
            """,
            [rfc],
        )

    # --- registros citados --------------------------------------------------

    def registro(self, tabla: str, record_id: str) -> dict | None:
        """
        Fila de `tabla` cuyo id coincide con `record_id`. En vendors y efos_list
        el RFC se busca normalizado, y el id devuelto es el valor crudo de la
        base, que es el que el validador compara.
        """
        pk = TABLE_PK[tabla]
        if tabla in ("vendors", "efos_list"):
            condicion = f"UPPER(TRIM({pk})) = UPPER(TRIM(?))"
        else:
            condicion = f"CAST({pk} AS VARCHAR) = ?"
        # tabla y pk vienen de TABLE_PK (lista cerrada), no de datos: por eso f-string.
        filas = self._filas(
            f"SELECT * FROM {tabla} WHERE {condicion} ORDER BY CAST({pk} AS VARCHAR) LIMIT 1",
            [str(record_id)],
        )
        return filas[0] if filas else None
