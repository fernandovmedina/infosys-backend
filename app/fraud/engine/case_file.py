"""
Case file para jueces: HTML autocontenido (sin red, sin scripts) generado a
partir del submission ya validado, con las secciones de case_file_structure.md.
El money trail se dibuja como SVG inline.
"""

from html import escape

from .catalogo import NOMBRE_ESQUEMA
from .evidencia import pesos
from .narrativa import TABLA_LLANA

ESTILO = """
:root { --tinta:#1d2430; --suave:#5b6573; --linea:#d9dee5; --fondo:#fbfbf8; --panel:#ffffff;
        --acento:#8a2c1b; --probable:#8a6a12; --probado:#8a2c1b; }
body { margin:0; background:var(--fondo); color:var(--tinta); font:15px/1.55 Georgia, 'Times New Roman', serif;
       padding-inline:16px; padding-block:32px; }
main { max-width:920px; margin:0 auto; }
h1, h2, h3 { font-family:'Helvetica Neue', Arial, sans-serif; line-height:1.25; }
h1 { font-size:1.9rem; margin:0 0 .25rem; }
h2 { font-size:1.35rem; border-bottom:2px solid var(--tinta); padding-bottom:.3rem; margin-top:2.6rem; }
h3 { font-size:1.1rem; margin:0; }
.sub { color:var(--suave); margin:0 0 1rem; }
.metricas { display:flex; flex-wrap:wrap; gap:.75rem; margin:1rem 0; }
.metrica { background:var(--panel); border:1px solid var(--linea); padding:.6rem .9rem; min-width:9rem; }
.metrica b { display:block; font:600 1.35rem 'Helvetica Neue', Arial, sans-serif; }
.metrica span { color:var(--suave); font-size:.85rem; }
table { border-collapse:collapse; width:100%; background:var(--panel); font-size:.9rem; }
th, td { border:1px solid var(--linea); padding:.45rem .6rem; text-align:left; vertical-align:top; }
th { font-family:'Helvetica Neue', Arial, sans-serif; background:#f0f1ee; }
td.num { text-align:right; font-variant-numeric:tabular-nums; white-space:nowrap; }
.tabla { overflow-x:auto; margin:.6rem 0 1rem; }
.finding { background:var(--panel); border:1px solid var(--linea); border-top:4px solid var(--acento);
           padding:1rem 1.2rem; margin:1.4rem 0; }
.etiqueta { display:inline-block; font:600 .75rem 'Helvetica Neue', Arial, sans-serif; letter-spacing:.04em;
            text-transform:uppercase; padding:.15rem .45rem; border:1px solid currentColor; }
.proven { color:var(--probado); } .probable { color:var(--probable); }
dl { display:grid; grid-template-columns:max-content 1fr; gap:.3rem 1rem; margin:.8rem 0; }
dt { font:600 .85rem 'Helvetica Neue', Arial, sans-serif; color:var(--suave); }
dd { margin:0; }
.diagrama { overflow-x:auto; border:1px solid var(--linea); background:#fff; margin:.5rem 0 1rem; }
.lead { border-left:3px solid var(--linea); padding:.2rem 0 .2rem 1rem; margin:1rem 0; }
.lead p { margin:.3rem 0; }
code { font-size:.85em; }
"""


def _e(valor) -> str:
    return escape(str(valor))


def _corto(texto: str, n: int = 34) -> str:
    return texto if len(texto) <= n else texto[: n - 1] + "…"


def diagrama_money_trail(pasos: list[dict], nombres: dict[str, str]) -> str:
    """Una fila por paso: caja origen -> flecha con monto, fecha y exhibit -> caja destino."""
    if not pasos:
        return "<p><em>This finding does not cite money movements traceable step by step.</em></p>"
    ancho_caja, alto_fila, x_destino = 250, 78, 470
    alto = alto_fila * len(pasos) + 10
    partes = [
        f'<svg role="img" aria-label="Money trail" viewBox="0 0 {x_destino + ancho_caja + 10} {alto}" '
        f'width="100%" style="min-width:640px" xmlns="http://www.w3.org/2000/svg" font-family="Helvetica, Arial, sans-serif">',
        '<defs><marker id="flecha" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
        'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#8a2c1b"/></marker></defs>',
    ]
    for i, p in enumerate(pasos):
        y = 10 + i * alto_fila
        for x, ident in ((5, p["from"]), (x_destino, p["to"])):
            nombre = " / ".join(
                filter(None, (nombres.get(parte.strip(), "") for parte in ident.split("/")))
            )
            partes.append(
                f'<rect x="{x}" y="{y}" width="{ancho_caja}" height="54" rx="4" fill="#f6f4ee" stroke="#1d2430"/>'
            )
            partes.append(
                f'<text x="{x + 10}" y="{y + 22}" font-size="13" font-weight="600" fill="#1d2430">{_e(_corto(ident))}</text>'
            )
            partes.append(
                f'<text x="{x + 10}" y="{y + 41}" font-size="12" fill="#5b6573">{_e(_corto(nombre or " "))}</text>'
            )
        x1, x2, ym = 5 + ancho_caja + 6, x_destino - 6, y + 27
        partes.append(
            f'<line x1="{x1}" y1="{ym}" x2="{x2}" y2="{ym}" stroke="#8a2c1b" stroke-width="2" marker-end="url(#flecha)"/>'
        )
        partes.append(
            f'<text x="{(x1 + x2) / 2}" y="{ym - 8}" font-size="13" font-weight="600" text-anchor="middle" fill="#1d2430">{_e(pesos(p["amount"]))}</text>'
        )
        partes.append(
            f'<text x="{(x1 + x2) / 2}" y="{ym + 18}" font-size="12" text-anchor="middle" fill="#5b6573">{_e(p["date"])} · {_e(p["exhibit_id"])}</text>'
        )
    partes.append("</svg>")
    return f'<div class="diagrama">{"".join(partes)}</div>'


def _seccion_finding(i: int, f: dict, anexo: dict) -> str:
    nombres = anexo["nombres"]
    titulo = ", ".join(
        f"{nombres.get(ent) or ent} ({ent})" if nombres.get(ent) else ent for ent in f["entities"]
    )
    filas_ex = "".join(
        f"<tr><td>{_e(ex['exhibit_id'])}</td><td><code>{_e(ex['source_table'])}</code></td>"
        f"<td><code>{_e(ex['record_id'])}</code></td><td>{_e(ex['note'])}</td></tr>"
        for ex in f["exhibits"]
    )
    reconciliacion = []
    for tabla, items in anexo["reconciliacion"].items():
        suma = sum(m for _, _, m in items)
        terminos = " + ".join(f"{pesos(m)} ({eid})" for eid, _, m in items)
        marca = " ← claimed amount" if tabla == anexo["tabla_monto"] else ""
        reconciliacion.append(
            f"<tr><td><code>{_e(tabla)}</code></td><td>{_e(terminos)}</td>"
            f"<td class='num'>{_e(pesos(suma))}</td><td>{_e(marca)}</td></tr>"
        )
    return f"""
<section class="finding" id="finding-{i}">
  <p class="sub">Finding {i} · {_e(NOMBRE_ESQUEMA[f["scheme_type"]])} (<code>{_e(f["scheme_type"])}</code>)</p>
  <h3>{_e(titulo)}</h3>
  <dl>
    <dt>Rule breached</dt><dd>{_e(f["rule_broken"])}</dd>
    <dt>Amount</dt><dd><b>{_e(pesos(f["peso_amount"]))}</b></dd>
    <dt>Confidence</dt><dd><span class="etiqueta {_e(f["confidence"])}">{_e(f["confidence"])}</span></dd>
    <dt>Detectors</dt><dd>{_e(", ".join(anexo["reglas"]))}</dd>
  </dl>
  <h4>What happened</h4>
  <p>{_e(f["narrative"])}</p>
  <h4>Money trail</h4>
  {diagrama_money_trail(f.get("money_trail") or [], nombres)}
  <h4>Exhibits</h4>
  <div class="tabla"><table><thead><tr><th>Exhibit</th><th>Table</th><th>Record</th><th>What it establishes</th></tr></thead>
  <tbody>{filas_ex}</tbody></table></div>
  <h4>Reconciliation</h4>
  <p>Amounts are totalled by table; an invoice and the payment that settled it are the same money viewed twice.
  The claimed amount ({_e(pesos(f["peso_amount"]))}) is the total of <code>{_e(anexo["tabla_monto"])}</code>
  ({_e(TABLA_LLANA.get(anexo["tabla_monto"], anexo["tabla_monto"]))}).</p>
  <div class="tabla"><table><thead><tr><th>Table</th><th>Exhibit sum</th><th>Total</th><th></th></tr></thead>
  <tbody>{"".join(reconciliacion)}</tbody></table></div>
</section>"""


def _seccion_leads(leads: list[dict], nombres: dict[str, str]) -> str:
    if not leads:
        return "<p>No open leads remain: no detector flagged an entity that was subsequently cleared.</p>"
    items = []
    for lead in leads:
        herramientas = ", ".join(lead.get("tool_calls_made") or []) or "none"
        titulo = (
            f"{nombres[lead['entity']]} ({lead['entity']})"
            if nombres.get(lead["entity"])
            else lead["entity"]
        )
        items.append(f"""
<div class="lead">
  <h3>{_e(titulo)}</h3>
  <p><b>What flagged it:</b> <code>{_e(lead["signal"])}</code></p>
  <p><b>Why it was not accused:</b> {_e(lead["reason"])}</p>
  <p><b>Queries performed:</b> <code>{_e(herramientas)}</code></p>
  <p><b>Closed by:</b> {_e(lead.get("closed_by", "investigator"))}</p>
</div>""")
    return "".join(items)


def render_case_file(submission: dict, anexos: list[dict], contexto: dict) -> str:
    meta = submission["run_metadata"]
    findings, leads = submission["findings"], submission["leads_not_pursued"]
    probados = sum(1 for f in findings if f["confidence"] == "proven")
    exposicion = sum(f["peso_amount"] for f in findings)
    inicio, fin = contexto["periodo"]
    empresa = contexto.get("empresa_nombre") or "Audited company"

    if findings:
        por_esquema = {}
        for f in findings:
            por_esquema[f["scheme_type"]] = por_esquema.get(f["scheme_type"], 0) + 1
        esquemas = "; ".join(f"{n} de {NOMBRE_ESQUEMA[s]}" for s, n in sorted(por_esquema.items()))
        resumen = (
            f"The system found {len(findings)} potential fraud scheme(s) ({esquemas}) totaling "
            f"{pesos(exposicion)}. {probados} are considered proven and {len(findings) - probados} probable. "
            f"It also reviewed and cleared {len(leads)} lead(s), each explained in section 4."
        )
    else:
        resumen = (
            f"The system found insufficient evidence to accuse anyone. It reviewed and cleared "
            f"{len(leads)} lead(s), each explained in section 4."
        )

    secciones_findings = (
        "".join(
            _seccion_finding(i, f, a) for i, (f, a) in enumerate(zip(findings, anexos), start=1)
        )
        or "<p>No findings in this run.</p>"
    )

    calidad = contexto.get("calidad") or {}
    filas_calidad = (
        "".join(
            f"<tr><td><code>{_e(r)}</code></td><td class='num'>{n}</td></tr>"
            for r, n in calidad.items()
        )
        or "<tr><td colspan='2'>No data-quality issues detected.</td></tr>"
    )
    fallidas = contexto.get("reglas_fallidas") or []
    texto_fallidas = (
        (
            "<p><b>Detectors that failed in this run</b> (their results were not considered): "
            + _e("; ".join(f"{n}: {err}" for n, err in fallidas))
            + "</p>"
        )
        if fallidas
        else ""
    )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Case file · seed {_e(submission["seed"])}</title>
<style>{ESTILO}</style>
</head>
<body>
<main>
<header>
  <h1>Forensic case file · {_e(empresa)}</h1>
  <p class="sub">RFC {_e(contexto.get("empresa_rfc") or "not identified")} · Audited period {_e(inicio or "?")} to {_e(fin or "?")} · Seed {_e(submission["seed"])}</p>
  <div class="metricas">
    <div class="metrica"><b>{_e(meta["llm_calls"])}</b><span>LLM calls</span></div>
    <div class="metrica"><b>{_e(pesos(meta["mxn_cost"]))}</b><span>MXN cost</span></div>
    <div class="metrica"><b>{_e(meta["wall_clock_seconds"])} s</b><span>execution time</span></div>
    <div class="metrica"><b>{"Yes" if meta.get("deterministic") else "No"}</b><span>deterministic run</span></div>
  </div>
</header>

<h2>2. Executive summary</h2>
<p>{_e(resumen)}</p>
<div class="tabla"><table><tbody>
  <tr><th>Findings</th><td>{len(findings)} ({probados} proven, {len(findings) - probados} probable)</td></tr>
  <tr><th>Total exposure</th><td>{_e(pesos(exposicion))}</td></tr>
  <tr><th>Investigated and closed leads</th><td>{len(leads)}</td></tr>
</tbody></table></div>
<p class="sub">If two findings share an entity (intertwined schemes), some money may appear in both.</p>

<h2>3. Findings</h2>
{secciones_findings}

<h2>4. Leads not pursued</h2>
{_seccion_leads(leads, contexto.get("nombres_pistas") or {})}

<h2>5. Method and limits</h2>
<p><b>Architecture.</b> {len(contexto.get("reglas_ejecutadas", []))} deterministic SQL detectors run against the DuckDB
estate and emit signals. An assembler groups signals by entity and scheme, and accuses only when there are at least two
independent evidence families (or one independently sufficient rule, such as a definitive EFOS listing or a payment to an
employee account) and no document explains the relationship. Each accusation cites at least 3 verified records and
reconciles its amount by table. Narratives are template-generated: no LLM is used anywhere in the process.</p>
<p><b>Out of scope for this run.</b> Text-similarity rules (generic descriptions, incompatible business activity, or a
vendor name similar to an employee name). Purchase-order splitting and revenue-inflation detectors are implemented.</p>
<p><b>What it cannot detect.</b> Schemes that leave no trace in the 8 tables; phantom vendors with complete purchase orders
and contracts and no other signal; money cycles through accounts outside the catalogs; or unrecorded cash payments. A
single signal is never enough to accuse, so a scheme with only one footprint remains a lead.</p>
{texto_fallidas}
<p><b>Data quality.</b> Issues found in the estate (they are not accusations, but may hide evidence):</p>
<div class="tabla"><table><thead><tr><th>Rule</th><th>Records</th></tr></thead><tbody>{filas_calidad}</tbody></table></div>
<p><b>Reproducibility.</b> Offline replay:
<code>uv run python -m app.fraud.engine.cli --input-dir &lt;csv-directory&gt; --seed {_e(submission["seed"])} --output-dir &lt;output-directory&gt;</code>.
The same CSV estate and seed produce the same findings and leads; only execution time changes.</p>
</main>
</body>
</html>
"""
