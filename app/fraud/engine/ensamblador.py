"""
Ensamblador: Signals -> clusters -> Finding interno o pista descartada.

1. Resuelve las entidades de cada Signal (RFC, empleado, cuenta sin dueño).
2. Por esquema, une en un cluster las entidades que aparecen juntas en algún
   Signal (union-find). Una entidad presente en dos esquemas genera dos
   clusters que la comparten (esquemas entrelazados), cada uno con su evidencia.
3. Decide: acusa si hay al menos dos familias de evidencia independientes, o
   una regla suficiente por sí sola, y no hay documentos que expliquen la
   relación; además exige 3 exhibits verificables con monto. Todo lo demás
   se convierte en pista descartada con una razón específica.
"""

import json
import math
from dataclasses import dataclass, field

import pandas as pd

from .catalogo import (
    CONFIDENCE,
    ESQUEMAS_DE_LA_EMPRESA,
    FAMILIA,
    FAMILIAS_ESQUEMA,
    FRASE_FAMILIA,
    MIN_EXHIBITS,
    NOMBRE_ESQUEMA,
    REGLAS_INTEGRIDAD,
    REGLAS_SUFICIENTES_SOLAS,
    RULE_TO_SCHEME,
)
from .cobertura import validate_entity_coverage
from .entidades import TIPOS_ACUSABLES, Entidad, Resolutor, format_entity_id
from .estate import Estate
from .evidencia import Citas, build_exhibits, citar_senal, compute_peso_amount, pesos

# Órdenes o asientos autorizados por un empleado señalado que se citan como contexto.
MAX_AUTORIZACIONES_CONTEXTO = 3


@dataclass
class Cluster:
    esquema: str
    entidades: list[Entidad]
    senales: list[dict]
    consultas: list[str] = field(default_factory=list)

    @property
    def reglas(self) -> list[str]:
        return sorted({s["rule_id"] for s in self.senales})

    @property
    def familias(self) -> list[str]:
        orden = FAMILIAS_ESQUEMA.get(self.esquema, [])
        fams = {FAMILIA.get(r) for r in self.reglas} - {None}
        return sorted(fams, key=lambda f: (orden.index(f) if f in orden else len(orden), f))

    @property
    def acusables(self) -> list[Entidad]:
        tipos = TIPOS_ACUSABLES | ({"empresa"} if self.esquema in ESQUEMAS_DE_LA_EMPRESA else set())
        return [e for e in self.entidades if e.tipo in tipos]

    @property
    def autosuficiencia(self) -> str:
        return (
            "autosuficiente"
            if any(s["autosuficiencia"] == "autosuficiente" for s in self.senales)
            else "presuntiva"
        )


@dataclass
class FindingInterno:
    cluster: Cluster
    exhibits: list[dict]
    peso_amount: float
    tabla_monto: str

    @property
    def confidence(self) -> str:
        return CONFIDENCE[self.cluster.autosuficiencia]


def senales_desde_df(signals: pd.DataFrame) -> list[dict]:
    senales = []
    for fila in signals.to_dict(orient="records"):
        fila["contexto"] = (
            json.loads(fila["contexto"]) if isinstance(fila.get("contexto"), str) else {}
        )
        monto = fila.get("monto")
        fila["monto"] = (
            None
            if monto is None or (isinstance(monto, float) and math.isnan(monto))
            else float(monto)
        )
        fila["evidence_id"] = None if fila.get("evidence_id") is None else str(fila["evidence_id"])
        senales.append(fila)
    senales.sort(
        key=lambda s: (
            s["rule_id"],
            str(s["fecha_deteccion"]),
            str(s["evidence_id"]),
            str(s["entity_id"]),
        )
    )
    return senales


class _UnionFind:
    def __init__(self):
        self.padre: dict[str, str] = {}

    def raiz(self, x: str) -> str:
        self.padre.setdefault(x, x)
        while self.padre[x] != x:
            self.padre[x] = self.padre[self.padre[x]]
            x = self.padre[x]
        return x

    def unir(self, a: str, b: str) -> None:
        ra, rb = self.raiz(a), self.raiz(b)
        if ra != rb:
            self.padre[max(ra, rb)] = min(ra, rb)


class Ensamblador:
    def __init__(self, estate: Estate):
        self.estate = estate
        self.resolutor = Resolutor(estate)
        self._nombres: dict[Entidad, str] = {}

    # --- nombres para texto -------------------------------------------------

    def nombre(self, ent: Entidad) -> str:
        if ent not in self._nombres:
            nombre = None
            if ent.tipo in ("rfc", "empresa"):
                filas = self.estate.vendors_por_rfc(ent.canonico)
                nombre = filas[0]["legal_name"] if filas else None
            elif ent.tipo == "employee":
                filas = self.estate.employee_por_id(ent.canonico) or self.estate.employee_por_id(
                    f"EMP:{ent.canonico}"
                )
                nombre = filas[0]["name"] if filas else None
            self._nombres[ent] = nombre or ""
        return self._nombres[ent]

    def etiqueta(self, ent: Entidad) -> str:
        ident = format_entity_id(ent.canonico, ent.tipo)
        nombre = self.nombre(ent)
        return f"{nombre} ({ident})" if nombre else ident

    # --- clusters -----------------------------------------------------------

    def esquema_de(self, sig: dict) -> str | None:
        """Esquema del Signal según RULE_TO_SCHEME, salvo el pago a empleado que cae en la CLABE de un proveedor."""
        if sig["rule_id"] == "PAYMENT_TO_EMPLOYEE_ACCOUNT" and self.estate.vendors_por_clabe(
            str(sig["contexto"].get("destino_clabe") or "").strip()
        ):
            # La empresa le pagó al "proveedor" y el dinero cayó en la cuenta del empleado:
            # es el mismo pago del proveedor fantasma, no una comisión aparte. Acusarlo
            # también como kickback reclamaría dos veces el mismo dinero.
            return "phantom_vendor"
        return RULE_TO_SCHEME.get(sig["rule_id"])

    def agrupar(self, senales: list[dict]) -> list[Cluster]:
        por_esquema: dict[str, list[tuple[dict, list[Entidad], list[str]]]] = {}
        for sig in senales:
            with self.estate.registrar() as consultas:
                esquema = self.esquema_de(sig)
                if esquema is None:
                    continue
                ents = self.resolutor.de_senal(sig)
            por_esquema.setdefault(esquema, []).append((sig, ents, list(consultas)))

        clusters = []
        for esquema in sorted(por_esquema):
            uf = _UnionFind()
            for sig, ents, _ in por_esquema[esquema]:
                llaves = [e.llave for e in ents if e.tipo != "empresa"] or [
                    f"sin_entidad:{sig['rule_id']}:{sig['evidence_id']}"
                ]
                for llave in llaves[1:]:
                    uf.unir(llaves[0], llave)
                sig["_raiz"] = uf.raiz(llaves[0])
            grupos: dict[str, Cluster] = {}
            for sig, ents, consultas in por_esquema[esquema]:
                raiz = uf.raiz(sig.pop("_raiz"))
                cl = grupos.setdefault(raiz, Cluster(esquema, [], []))
                cl.senales.append(sig)
                cl.entidades = sorted(set(cl.entidades) | set(ents))
                cl.consultas += [c for c in consultas if c not in cl.consultas]
            clusters += [grupos[r] for r in sorted(grupos)]
        return clusters

    # --- decisión -------------------------------------------------------------

    def resolver(self, cluster: Cluster) -> tuple[FindingInterno | None, dict | None]:
        """Devuelve (finding, None) si se acusa o (None, pista) si se descarta."""
        with self.estate.registrar() as consultas:
            resultado = self._decidir(cluster)
        cluster.consultas += [c for c in consultas if c not in cluster.consultas]
        if isinstance(resultado, FindingInterno):
            return resultado, None
        return None, self._pista(cluster, resultado)

    def _decidir(self, cl: Cluster):
        if not cl.acusables:
            no_empresa = [e for e in cl.entidades if e.tipo != "empresa"]
            return ("no_resuelta", no_empresa) if no_empresa else ("solo_empresa", None)

        familias = cl.familias
        suficientes = set(cl.reglas) & REGLAS_SUFICIENTES_SOLAS
        if len(familias) < 2 and not suficientes:
            return (
                "senal_unica",
                self._materialidad(cl) if cl.esquema == "phantom_vendor" else None,
            )

        if cl.esquema == "phantom_vendor" and "cuenta_compartida" not in familias:
            respaldo = self._materialidad(cl)
            if respaldo:
                return ("materialidad", respaldo)

        citas = self._citas(cl)
        exhibits = build_exhibits(self.estate, citas)
        if len(exhibits) < MIN_EXHIBITS:
            return ("exhibits_insuficientes", exhibits)
        cobertura = validate_entity_coverage(self.estate, cl.acusables, exhibits)
        if cobertura:
            return ("entidad_sin_respaldo", cobertura)
        monto = compute_peso_amount(cl.esquema, exhibits)
        if monto is None:
            return ("sin_monto", exhibits)
        return FindingInterno(cl, exhibits, monto[0], monto[1])

    def _materialidad(self, cl: Cluster) -> dict | None:
        """Órdenes y contratos de cada RFC señalado; solo exculpa si todos los tienen."""
        respaldo = {}
        for ent in cl.acusables:
            if ent.tipo != "rfc":
                return None
            ordenes, contratos = (
                self.estate.ordenes_por_rfc(ent.canonico),
                self.estate.contratos_por_rfc(ent.canonico),
            )
            if not ordenes or not contratos:
                return None
            respaldo[ent] = (ordenes, contratos)
        return respaldo

    def _citas(self, cl: Cluster) -> Citas:
        citas = Citas()
        for sig in cl.senales:
            citar_senal(citas, sig)
            if sig["rule_id"] in ("BANK_CYCLE_2NODE", "BANK_CYCLE_NNODE"):
                # La factura que pagó la salida del ciclo mide el monto circulado; sin ella,
                # peso_amount sumaría todos los saltos (el mismo dinero de ida y de vuelta).
                for fac in self.estate.facturas_pagadas_por(str(sig["evidence_id"])):
                    citas.agregar(
                        "invoices",
                        fac["uuid"],
                        f"is the invoice paid by transfer {sig['evidence_id']}, which starts the cycle",
                    )
        for ent in cl.acusables:
            if ent.tipo == "rfc":
                vendors = self.estate.vendors_por_rfc(ent.canonico)
                if vendors:
                    citas.agregar(
                        "vendors",
                        ent.canonico,
                        "identifies the flagged vendor and the account it receives payments into",
                        solo_si_nuevo=True,
                    )
                if self.estate.efos_por_rfc(ent.canonico):
                    citas.agregar("efos_list", ent.canonico)
                if cl.esquema == "phantom_vendor":
                    # Si el proveedor es fantasma, toda su facturación y todo lo que se le pagó es simulado.
                    for fac in self.estate.facturas_emitidas_por(ent.canonico):
                        citas.agregar(
                            "invoices",
                            fac["uuid"],
                            "another invoice issued by the flagged vendor",
                            solo_si_nuevo=True,
                        )
                    for v in vendors:
                        if v.get("bank_clabe"):
                            for txn in self.estate.pagos_a_clabe(str(v["bank_clabe"]).strip()):
                                citas.agregar(
                                    "bank_txns",
                                    txn["txn_id"],
                                    "payment to the registered account of the flagged vendor",
                                    solo_si_nuevo=True,
                                )
            elif ent.tipo == "employee":
                filas = self.estate.employee_por_id(ent.canonico) or self.estate.employee_por_id(
                    f"EMP:{ent.canonico}"
                )
                if filas:
                    emp = filas[0]
                    citas.agregar(
                        "employees",
                        emp["emp_id"],
                        "identifies the flagged employee and their bank account",
                        solo_si_nuevo=True,
                    )
                    if cl.esquema == "threshold_splitting":
                        # Las órdenes fraccionadas ya muestran quién autorizó; otras órdenes
                        # suyas inflarían el total de purchase_orders que se reclama.
                        continue
                    # Contexto no acusatorio: muestra que el empleado autoriza compras o gastos.
                    for aut in self.estate.autorizaciones_de(
                        str(emp["name"] or ""), MAX_AUTORIZACIONES_CONTEXTO
                    ):
                        citas.agregar(
                            aut["tabla"],
                            aut["id"],
                            f"shows that {emp['name']} ({emp['role']}) requests or approves "
                            f"the company's purchasing transactions",
                            solo_si_nuevo=True,
                        )
        return citas

    # --- pistas descartadas ---------------------------------------------------

    def cancelaciones_descartadas(self, findings: list[FindingInterno]) -> list[dict]:
        """
        Cuando se acusa a la empresa de inflar ingresos, deja constancia de sus otras
        facturas canceladas que sí se revirtieron: se revisaron y no entran al monto.
        """
        pistas = []
        empresas = sorted(
            {
                e
                for fi in findings
                if fi.cluster.esquema == "revenue_inflation"
                for e in fi.cluster.acusables
                if e.tipo == "empresa"
            }
        )
        for ent in empresas:
            with self.estate.registrar() as consultas:
                revertidas = self.estate.cancelaciones_revertidas(ent.canonico)
            for fac in revertidas:
                pistas.append(
                    {
                        "entity": format_entity_id(ent.canonico, ent.tipo),
                        "signal": "INFLATE_AND_CANCEL",
                        "reason": (
                            f"Invoice {fac['uuid']} from {self.etiqueta(ent)} for {pesos(fac['total'])}, dated "
                            f"{fac['issue_date']}, is also cancelled, but its {int(fac['renglones'])} ledger entries "
                            f"were reversed and leave revenue, IVA, and accounts receivable at zero. "
                            f"This is a properly recorded cancellation: it is not part of the revenue inflation or the claimed amount."
                        ),
                        "tool_calls_made": ["rule_inflate_and_cancel"] + list(consultas),
                        "closed_by": "investigator",
                    }
                )
        return pistas

    def _detalle(self, cl: Cluster) -> str:
        partes = []
        for regla in cl.reglas:
            senales = [s for s in cl.senales if s["rule_id"] == regla]
            ids = sorted({str(s["evidence_id"]) for s in senales})
            muestra = ", ".join(ids[:3]) + (f" and {len(ids) - 3} more" if len(ids) > 3 else "")
            montos = [s["monto"] for s in senales if s["monto"] is not None]
            monto = f", {pesos(sum(montos))}" if montos else ""
            partes.append(f"{regla} in {muestra}{monto}")
        return "; ".join(partes)

    @staticmethod
    def _texto_materialidad(respaldo: dict) -> str:
        docs = []
        for ent, (ordenes, contratos) in respaldo.items():
            docs.append(
                f"{format_entity_id(ent.canonico, ent.tipo)} has {len(ordenes)} purchase order(s) "
                f"({', '.join(o['po_id'] for o in ordenes[:3])}) and {len(contratos)} contract(s) "
                f"({', '.join(c['contract_id'] for c in contratos[:3])})"
            )
        return "; ".join(docs)

    def _pista(self, cl: Cluster, motivo: tuple) -> dict:
        clave, datos = motivo
        principal = (
            cl.acusables
            or [e for e in cl.entidades if e.tipo != "empresa"]
            or cl.entidades
            or [None]
        )[0]
        nombre = self.etiqueta(principal) if principal else "No identifiable entity"
        otros = [self.etiqueta(e) for e in cl.acusables if e != principal]
        con_otros = f" (together with {', '.join(otros)})" if otros else ""
        detalle = self._detalle(cl)
        frases = [FRASE_FAMILIA[f] for f in cl.familias]
        esquema = NOMBRE_ESQUEMA[cl.esquema]

        if clave == "senal_unica":
            faltantes = [
                FRASE_FAMILIA[f] for f in FAMILIAS_ESQUEMA[cl.esquema] if f not in cl.familias
            ]
            razon = (
                f"{nombre}{con_otros} has only one signal: {frases[0] if frases else 'derived from another rule'} ({detalle}). "
                f"To accuse {esquema}, we require a second independent signal "
                f"(one that {'; or that '.join(faltantes[:3])}), and no rule found one."
            )
            if datos:
                razon += f" In addition, {self._texto_materialidad(datos)} documenting the commercial relationship."
        elif clave == "materialidad":
            razon = (
                f"{nombre}{con_otros} triggered {detalle}, but {self._texto_materialidad(datos)} documenting "
                f"a real commercial relationship, and does not share a bank account with another vendor."
            )
        elif clave == "exhibits_insuficientes":
            ids = ", ".join(f"{e['source_table']}.{e['record_id']}" for e in datos) or "ninguno"
            razon = (
                f"{nombre}{con_otros}: {detalle}. There are only {len(datos)} citable record(s) ({ids}); "
                f"at least {MIN_EXHIBITS} verifiable records are required to support an accusation."
            )
        elif clave == "sin_monto":
            ids = ", ".join(f"{e['source_table']}.{e['record_id']}" for e in datos)
            razon = (
                f"{nombre}{con_otros}: {detalle}. None of the citable records ({ids}) is an invoice, "
                f"payment, order, or contract with an amount, so there is no monetary harm to claim."
            )
        elif clave == "entidad_sin_respaldo":
            faltantes_texto = "; ".join(
                f"{self.etiqueta(item.entity)}: missing {item.requirement}" for item in datos
            )
            razon = (
                f"{nombre}{con_otros}: {detalle}. The candidate exhibits were reviewed, "
                f"but they do not all prove each accused entity's involvement ({faltantes_texto}). "
                "The signal is closed as a lead to avoid attributing a transaction without documentary support."
            )
        elif clave == "no_resuelta":
            cuentas = ", ".join(format_entity_id(e.canonico, e.tipo) for e in datos)
            razon = (
                f"{detalle}. The accounts or people involved ({cuentas}) do not correspond to any "
                f"vendor or employee in the catalogs, so there is no identifiable party to accuse."
            )
        elif clave == "solo_empresa":
            razon = (
                f"{detalle}. All accounts and RFCs involved belong to the audited company "
                f"({self.estate.empresa_rfc}), so this is an internal movement, not a third-party scheme."
            )
        else:
            raise ValueError(f"Decline reason without a template: {clave}")

        return {
            "entity": format_entity_id(principal.canonico, principal.tipo)
            if principal
            else "SIN_ENTIDAD",
            "signal": ", ".join(cl.reglas),
            "reason": razon,
            "tool_calls_made": [f"rule_{r.lower()}" for r in cl.reglas] + cl.consultas,
            "closed_by": "investigator",
        }


def ensamblar(
    estate: Estate, signals: pd.DataFrame
) -> tuple[list[FindingInterno], list[dict], dict[str, int]]:
    """Devuelve (findings internos, pistas descartadas, conteo de señales de calidad de datos)."""
    senales = senales_desde_df(signals)
    calidad = {}
    for s in senales:
        if s["rule_id"] in REGLAS_INTEGRIDAD:
            calidad[s["rule_id"]] = calidad.get(s["rule_id"], 0) + 1

    ensamblador = Ensamblador(estate)
    findings, pistas = [], []
    for cluster in ensamblador.agrupar(senales):
        finding, pista = ensamblador.resolver(cluster)
        if finding:
            findings.append(finding)
        else:
            pistas.append(pista)
    pistas += ensamblador.cancelaciones_descartadas(findings)
    return findings, pistas, dict(sorted(calidad.items()))
