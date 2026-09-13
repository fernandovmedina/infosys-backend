"""
Resolución de entidades: convierte el entity_id heterogéneo de cada Signal
(RFC, CLABE, emp_id, nombre de aprobador) en entidades canónicas con tipo,
y las serializa al formato con prefijo que exige el submission.
"""

from dataclasses import dataclass

from .estate import Estate

# rfc y employee son acusables; empresa es la auditada; clabe y persona son
# cuentas o nombres sin dueño en los catálogos.
TIPOS_ACUSABLES = {"rfc", "employee"}


@dataclass(frozen=True, order=True)
class Entidad:
    tipo: str
    canonico: str

    @property
    def llave(self) -> str:
        return f"{self.tipo}:{self.canonico}"


def format_entity_id(entity_canonical_id: str, entity_type: str) -> str:
    """Id con prefijo por tipo, p. ej. 'RFC:AAAA010101AA1' o 'EMP:0001'."""
    prefixes = {
        "rfc": "RFC",
        "employee": "EMP",
        "empresa": "RFC",
        "clabe": "CLABE",
        "persona": "PERSONA",
    }
    if entity_type not in prefixes:
        raise ValueError(f"Tipo de entidad sin prefijo definido: {entity_type}")
    return f"{prefixes[entity_type]}:{entity_canonical_id}"


def _canonico_emp(emp_id: str) -> str:
    emp_id = str(emp_id).strip()
    return emp_id.split(":", 1)[1] if emp_id.upper().startswith("EMP:") else emp_id


def _separar(texto, sep: str) -> list[str]:
    return [p.strip() for p in str(texto or "").split(sep) if p.strip()]


class Resolutor:
    def __init__(self, estate: Estate):
        self.estate = estate

    def rfc(self, rfc) -> list[Entidad]:
        rfc = str(rfc or "").strip().upper()
        if not rfc:
            return []
        if rfc == self.estate.empresa_rfc:
            return [Entidad("empresa", rfc)]
        return [Entidad("rfc", rfc)]

    def empleado(self, emp_id) -> list[Entidad]:
        emp_id = str(emp_id or "").strip()
        return [Entidad("employee", _canonico_emp(emp_id))] if emp_id else []

    def clabe(self, clabe) -> list[Entidad]:
        clabe = str(clabe or "").strip()
        if not clabe:
            return []
        if clabe in self.estate.empresa_clabes:
            return [Entidad("empresa", self.estate.empresa_rfc or clabe)]
        duenos = [e for v in self.estate.vendors_por_clabe(clabe) for e in self.rfc(v["rfc"])]
        duenos += [
            e
            for emp in self.estate.employees_por_clabe(clabe)
            for e in self.empleado(emp["emp_id"])
        ]
        return sorted(set(duenos)) or [Entidad("clabe", clabe)]

    def persona(self, nombre) -> list[Entidad]:
        nombre = str(nombre or "").strip()
        if not nombre:
            return []
        empleados = self.estate.employees_por_nombre(nombre)
        if empleados:
            return [e for emp in empleados for e in self.empleado(emp["emp_id"])]
        return [Entidad("persona", nombre)]

    def de_senal(self, sig: dict) -> list[Entidad]:
        """Todas las entidades que involucra un Signal, según cómo lo arma su regla."""
        regla, ctx, eid = sig["rule_id"], sig["contexto"], sig["entity_id"]
        if regla == "SHARED_CLABE_MULTI_RFC":
            ents = [e for r in _separar(ctx.get("rfcs_involucrados"), ",") for e in self.rfc(r)]
        elif regla == "PAYMENT_TO_EMPLOYEE_ACCOUNT":
            # Además del empleado: el proveedor que registró esa misma CLABE (empleado
            # disfrazado de proveedor) o el proveedor que le transfirió (comisión).
            ents = (
                self.empleado(eid)
                + self.clabe(ctx.get("destino_clabe"))
                + self.clabe(ctx.get("origen_clabe"))
            )
            ents = [e for e in ents if e.tipo != "clabe"]
        elif regla == "APPROVER_VENDOR_CONCENTRATION":
            ents = self.persona(eid) + self.rfc(ctx.get("vendor_rfc"))
        elif regla == "NO_SEGREGATION_OF_DUTIES":
            ents = self.persona(eid) + self.rfc(ctx.get("vendor_rfc"))
        elif regla == "BANK_CYCLE_2NODE":
            ents = self.clabe(eid) + self.clabe(ctx.get("clabe_origen"))
        elif regla == "BANK_CYCLE_NNODE":
            ents = [e for c in _separar(ctx.get("ruta_clabes"), "->") for e in self.clabe(c)]
        elif regla == "CYCLE_LEAKAGE_RATE":
            ents = self.clabe(eid) + [
                e for c in _separar(ctx.get("clabes_origen"), ",") for e in self.clabe(c)
            ]
        elif regla == "SAME_APPROVER_SPLIT":
            ents = self.rfc(eid) + self.persona(ctx.get("approver"))
        elif regla == "CONTRACT_SPLIT_INTO_POS":
            ents = self.rfc(eid) + [
                e for n in _separar(ctx.get("aprobadores"), ",") for e in self.persona(n)
            ]
        elif regla == "INFLATE_AND_CANCEL":
            ents = self.rfc(eid) + self.rfc(ctx.get("receiver_rfc"))
        elif regla == "AR_AGING_EXCESSIVE":
            ents = self.rfc(eid) + self.rfc(ctx.get("issuer_rfc"))
        elif regla == "BANK_TXN_NOT_IN_LEDGER":
            ents = self.clabe(eid)
        elif regla == "INVOICE_BIDIRECTIONAL":
            ents = self.rfc(eid) + self.rfc(ctx.get("rfc_contraparte"))
        else:
            ents = self.rfc(eid)
        return sorted(set(ents))
