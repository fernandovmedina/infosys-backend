"""
Tablas estáticas del agente: de qué esquema es indicio cada regla, qué evidencia
es independiente de cuál, qué norma se viola y cómo se leen las tablas del estate.

Todo aquí se declara a mano a partir del catálogo de reglas; nada se infiere
comparando contra respuestas esperadas.
"""

RULE_TO_SCHEME = {
    "EFOS_DIRECT_MATCH": "phantom_vendor",
    "EFOS_PRESUNTO_MATCH": "phantom_vendor",
    "EFOS_POST_DATED": "phantom_vendor",
    "VENDOR_SHORT_LIFECYCLE": "phantom_vendor",
    "INVOICE_NO_PO_NO_CONTRACT": "phantom_vendor",
    "SHARED_CLABE_MULTI_RFC": "phantom_vendor",
    # Es la salida de dinero hacia un EFOS o CLABE compartida: el pago al fantasma.
    "OUTBOUND_TO_SUSPECT_ENTITY": "phantom_vendor",
    # Si la CLABE del empleado está registrada a un proveedor, el ensamblador lo
    # cuenta como phantom_vendor (ver Ensamblador.esquema_de).
    "PAYMENT_TO_EMPLOYEE_ACCOUNT": "kickback",
    "APPROVER_VENDOR_CONCENTRATION": "kickback",
    "NO_SEGREGATION_OF_DUTIES": "kickback",
    "PRICE_OUTLIER_BY_CATEGORY": "kickback",
    "BANK_CYCLE_2NODE": "round_tripping",
    "BANK_CYCLE_NNODE": "round_tripping",
    "CYCLE_LEAKAGE_RATE": "round_tripping",
    "INVOICE_BIDIRECTIONAL": "round_tripping",
    # El dinero que vuelve sin asiento contable es la vuelta del ciclo.
    "BANK_TXN_NOT_IN_LEDGER": "round_tripping",
    "PO_NEAR_THRESHOLD": "threshold_splitting",
    "PO_WINDOW_SUM_SPLIT": "threshold_splitting",
    "BANK_TXN_WINDOW_SPLIT": "threshold_splitting",
    "SAME_APPROVER_SPLIT": "threshold_splitting",
    "CONTRACT_SPLIT_INTO_POS": "threshold_splitting",
    "BENFORD_DEVIATION_TOTAL": "threshold_splitting",
    "BENFORD_DEVIATION_BANK": "threshold_splitting",
    "INVOICE_NO_COLLECTION": "revenue_inflation",
    "AR_AGING_EXCESSIVE": "revenue_inflation",
    "PERIOD_END_SPIKE": "revenue_inflation",
    "RECEIVER_NO_PAYMENT_HISTORY": "revenue_inflation",
    "INFLATE_AND_CANCEL": "revenue_inflation",
    "RECEIVER_IN_EFOS": "revenue_inflation",
}

# Reglas de calidad de datos: no son indicio de un esquema, se reportan aparte.
REGLAS_INTEGRIDAD = {
    "LEDGER_UNBALANCED_ENTRY",
    "ORPHAN_INVOICE_UUID",
    "MALFORMED_RFC",
    "CLABE_INVALID_LENGTH",
}

# Familia de evidencia de cada regla. Un cluster se acusa solo si lo sostienen
# al menos dos familias distintas: dos reglas que miran el mismo hecho (p. ej.
# EFOS definitivo y EFOS con factura previa a la publicación) no se corroboran
# entre sí. None = regla derivada de otra, no suma una familia.
FAMILIA = {
    "EFOS_DIRECT_MATCH": "lista_sat",
    "EFOS_PRESUNTO_MATCH": "lista_sat",
    "EFOS_POST_DATED": "lista_sat",
    "VENDOR_SHORT_LIFECYCLE": "alta_reciente",
    "INVOICE_NO_PO_NO_CONTRACT": "sin_materialidad",
    "SHARED_CLABE_MULTI_RFC": "cuenta_compartida",
    "OUTBOUND_TO_SUSPECT_ENTITY": None,
    "PAYMENT_TO_EMPLOYEE_ACCOUNT": "pago_a_empleado",
    "APPROVER_VENDOR_CONCENTRATION": "concentracion_aprobador",
    "NO_SEGREGATION_OF_DUTIES": "segregacion",
    "PRICE_OUTLIER_BY_CATEGORY": "sobreprecio",
    "BANK_CYCLE_2NODE": "ciclo_bancario",
    "BANK_CYCLE_NNODE": "ciclo_bancario",
    "CYCLE_LEAKAGE_RATE": "comision_repetida",
    "INVOICE_BIDIRECTIONAL": "factura_espejo",
    "BANK_TXN_NOT_IN_LEDGER": "sin_registro_contable",
    "SAME_APPROVER_SPLIT": "ordenes_fraccionadas",
    "CONTRACT_SPLIT_INTO_POS": "contrato_fraccionado",
    "INFLATE_AND_CANCEL": "cancelada_sin_reversion",
    "AR_AGING_EXCESSIVE": "cxc_sin_cobro",
}

# Esquemas cometidos por la propia empresa auditada: su RFC es acusable además de
# la contraparte (en los demás, la empresa es la víctima y nunca se acusa).
ESQUEMAS_DE_LA_EMPRESA = {"revenue_inflation"}

# Reglas que bastan solas para acusar: el hecho que prueban ya es el esquema
# (el SAT ya declaró al proveedor EFOS; la empresa pagó a la cuenta de un empleado).
REGLAS_SUFICIENTES_SOLAS = {"EFOS_DIRECT_MATCH", "PAYMENT_TO_EMPLOYEE_ACCOUNT"}

# Frase en lenguaje llano de cada familia, para narrativas y razones de descarte.
FRASE_FAMILIA = {
    "lista_sat": "appears on the SAT list of taxpayers suspected of issuing invoices for simulated transactions",
    "alta_reciente": "began invoicing soon after registration",
    "sin_materialidad": "has no purchase order or contract with the audited company",
    "cuenta_compartida": "receives payments into a bank account also registered to another vendor",
    "pago_a_empleado": "the company transferred funds directly to an employee's bank account",
    "concentracion_aprobador": "one employee approved many of its invoices",
    "segregacion": "the same person requested and approved its purchase orders",
    "sobreprecio": "charged far above other vendors in its category",
    "ciclo_bancario": "funds sent out returned to the originating account within a few days",
    "comision_repetida": "funds circulated repeatedly while leaving a small commission each time",
    "factura_espejo": "the parties invoiced each other for nearly identical amounts",
    "sin_registro_contable": "funds returned to the company do not appear in its ledger",
    "ordenes_fraccionadas": "the same person approved consecutive purchase orders to the same vendor that together exceed the limit",
    "contrato_fraccionado": "one contract was requested through several smaller purchase orders",
    "cancelada_sin_reversion": "cancelled sales invoices remain recorded as revenue in the ledger",
    "cxc_sin_cobro": "the receivables from those sales have remained open for months with no collection",
}

# Familias que se esperan para corroborar cada esquema (para explicar descartes).
FAMILIAS_ESQUEMA = {
    "phantom_vendor": [
        "lista_sat",
        "alta_reciente",
        "sin_materialidad",
        "cuenta_compartida",
        "pago_a_empleado",
    ],
    "kickback": ["pago_a_empleado", "concentracion_aprobador", "segregacion", "sobreprecio"],
    "round_tripping": [
        "ciclo_bancario",
        "comision_repetida",
        "factura_espejo",
        "sin_registro_contable",
    ],
    "threshold_splitting": ["ordenes_fraccionadas", "contrato_fraccionado"],
    "revenue_inflation": ["cancelada_sin_reversion", "cxc_sin_cobro"],
}

NOMBRE_ESQUEMA = {
    "phantom_vendor": "phantom vendor",
    "kickback": "kickback or improper commission",
    "round_tripping": "round tripping",
    "threshold_splitting": "purchase-order splitting",
    "revenue_inflation": "revenue inflation",
}

# Norma específica que sostiene la acusación, por esquema.
RULE_BROKEN = {
    "phantom_vendor": "Mexican Federal Fiscal Code (CFF), Article 69-B (non-existent transactions supported by EFOS invoices)",
    "kickback": "Mexican Income Tax Law (LISR), Article 27(I) (expense not strictly necessary) and Federal Criminal Code, Article 386 (fraud)",
    "round_tripping": "Mexican Federal Fiscal Code (CFF), Article 69-B (simulated transactions without economic substance)",
    "threshold_splitting": "Internal purchase-approval limit policy (splitting to evade a control)",
    "revenue_inflation": "Mexican Federal Fiscal Code (CFF), Article 28(I) (accounting must record real transactions)",
}

# Llave primaria y columna de monto de cada tabla (mismas que usa validate_format.py).
TABLE_PK = {
    "ledger": "entry_id",
    "invoices": "uuid",
    "bank_txns": "txn_id",
    "vendors": "rfc",
    "efos_list": "rfc",
    "purchase_orders": "po_id",
    "contracts": "contract_id",
    "employees": "emp_id",
}
AMOUNT_COLUMN = {
    "invoices": "total",
    "bank_txns": "amount",
    "purchase_orders": "amount",
    "contracts": "value",
}

# Tabla cuyo total se reclama como peso_amount, en orden de preferencia por
# esquema. Nunca se suman tablas entre sí: una factura y su pago son el mismo dinero.
PRIORIDAD_MONTO = {
    # El monto simulado es lo facturado por el fantasma; el pago puede ser parcial.
    "phantom_vendor": ["invoices", "bank_txns", "purchase_orders", "contracts"],
    # El beneficio indebido es el dinero que llegó al empleado o al proveedor.
    "kickback": ["bank_txns", "invoices", "purchase_orders", "contracts"],
    # La factura que disfraza el retorno mide el monto circulado; si no hay,
    # se usan los movimientos bancarios del ciclo (incluye ida y vuelta).
    "round_tripping": ["invoices", "bank_txns", "purchase_orders", "contracts"],
    "threshold_splitting": ["purchase_orders", "bank_txns", "invoices", "contracts"],
    "revenue_inflation": ["invoices", "bank_txns", "purchase_orders", "contracts"],
}

# Orden de presentación de exhibits: primero los que llevan monto.
ORDEN_TABLAS = [
    "invoices",
    "bank_txns",
    "purchase_orders",
    "contracts",
    "ledger",
    "vendors",
    "efos_list",
    "employees",
]

CONFIDENCE = {"autosuficiente": "proven", "presuntiva": "probable"}
MIN_EXHIBITS = 3
MAX_PALABRAS_NARRATIVA = 150
TOLERANCIA_PESOS = 0.02
