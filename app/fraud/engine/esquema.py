"""
Esquema del estate (réplica de estate_schema.sql sin claves primarias): DDL de las 8
tablas en el orden en que se crean y se cargan. Lo usan la ingesta de CSV, el script
scripts/crear_db.py y la carga de escenarios.
"""

TABLES = {
    "vendors": """
        CREATE TABLE IF NOT EXISTS vendors (
            rfc             TEXT,
            legal_name      TEXT,
            registered_date TEXT,
            address         TEXT,
            bank_clabe      TEXT,
            category        TEXT,
            contact_email   TEXT
        )
    """,
    "invoices": """
        CREATE TABLE IF NOT EXISTS invoices (
            uuid          TEXT,
            issuer_rfc    TEXT,
            receiver_rfc  TEXT,
            issue_date    TEXT,
            subtotal      REAL,
            iva           REAL,
            total         REAL,
            concepto_text TEXT,
            uso_cfdi      TEXT,
            forma_pago    TEXT,
            metodo_pago   TEXT,
            status        TEXT
        )
    """,
    "ledger": """
        CREATE TABLE IF NOT EXISTS ledger (
            entry_id     INTEGER,
            date         TEXT,
            account_code TEXT,
            account_name TEXT,
            debit        REAL,
            credit       REAL,
            description  TEXT,
            invoice_uuid TEXT,
            cost_center  TEXT,
            approver     TEXT
        )
    """,
    "bank_txns": """
        CREATE TABLE IF NOT EXISTS bank_txns (
            txn_id     TEXT,
            date       TEXT,
            from_clabe TEXT,
            to_clabe   TEXT,
            amount     REAL,
            reference  TEXT,
            channel    TEXT
        )
    """,
    "purchase_orders": """
        CREATE TABLE IF NOT EXISTS purchase_orders (
            po_id       TEXT,
            vendor_rfc  TEXT,
            date        TEXT,
            amount      REAL,
            requester   TEXT,
            approver    TEXT,
            description TEXT
        )
    """,
    "contracts": """
        CREATE TABLE IF NOT EXISTS contracts (
            contract_id TEXT,
            vendor_rfc  TEXT,
            start_date  TEXT,
            value       REAL,
            scope_text  TEXT
        )
    """,
    "employees": """
        CREATE TABLE IF NOT EXISTS employees (
            emp_id     TEXT,
            name       TEXT,
            role       TEXT,
            bank_clabe TEXT,
            hire_date  TEXT
        )
    """,
    "efos_list": """
        CREATE TABLE IF NOT EXISTS efos_list (
            rfc              TEXT,
            legal_name       TEXT,
            status           TEXT,
            publication_date TEXT
        )
    """,
}
