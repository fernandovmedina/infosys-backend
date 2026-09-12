# The problem today

Invoice fraud in Mexico is not a neat list of flagged rows. It is a
scheme hidden inside a real company's books: a fake supplier billing for
work never done, a kickback routed through a shell company, or sales
faked to inflate the numbers. Mexico's tax authority, SAT, publishes a
blacklist of fake-invoice companies under Article 69-B, but by the time
a supplier appears on it, the company has already claimed the deductions
and is on the hook. Today's tools flag odd items one at a time and leave
a person to connect them. Nobody follows the money all the way, nobody
builds the proof, and honest suppliers who simply look odd get accused
too.

# The big challenge

Given a company's books and only the hint that something is wrong, can
an AI agent find the fraud, follow the money, and prove it, without
accusing anyone it cannot back up?

# Possible approaches

1.  Investigate step by step: from a theory, search the ledger,
    invoices, and bank records, follow a lead, and change course when it
    dead-ends.
2.  Use simple detectors (blacklisted suppliers, payments that do not
    match invoices, money that moves in a circle) to point the agent at
    what is worth digging into.
3.  Build an evidence trail for every accusation and refuse to name a
    supplier it cannot back with a clear rule broken and a peso amount.

# Resources for hackers

Teams build on real, free resources that exist online. SAT publishes the
official Article 69-B list of companies that issue fake invoices (EFOS),
a real, downloadable Mexican dataset, along with the CFDI 4.0 invoice
schemas. IBM AMLSim (open-source) generates the money-flow rings and
shell-company patterns behind kickbacks and round-tripping. Public
financial-fraud datasets, such as the IEEE-CIS set on Kaggle, give
baselines for the anomaly checks. Teams assemble a company data state
from these pieces, a ledger, invoices, bank records, and a supplier
list, then build the investigation loop.

**Note on tools:** this track makes many AI calls per investigation, so
a local model (Ollama) with caching is safer than the Gemini free tier
alone, which can hit daily limits.

# What to build

A forensic agent that investigates records it has never seen and hands
in a case file: the scheme, the suppliers involved, the evidence trail,
and the peso amount, plus a short list of leads it chose not to chase
and why. Deliver working code and a 3-minute live demo where judges hide
a fresh scheme in the data, the agent traces the money on screen, then
answers one surprise question about its reasoning.

# Why it matters

Every peso lost to fake invoices is taken from an honest business and
the public purse, and every supplier wrongly accused loses a customer
for no reason. An agent that investigates and proves, instead of just
flagging, is the difference between a report that falls apart and a case
a company can act on. This is the forensic work Infosys does at scale,
and proving before accusing is what separates a real auditor from a
guesser.

# Judging criteria

-   **Results:** on records it has never seen, how much hidden fraud
    does the agent find and correctly prove?
-   **Judgment:** does it refuse to accuse suppliers it cannot back up,
    and can it defend a finding when a judge asks?
-   **Feasibility:** could a real finance or audit team trust and use
    this?
-   **Clarity:** is the case file easy to follow, with a clear money
    trail?

------------------------------------------------------------------------

# El problema actual

El fraude con facturas en México no es una lista limpia de filas
marcadas. Es un esquema oculto dentro de la contabilidad de una empresa
real: un proveedor falso que factura por un trabajo que nunca se
realizó, un moche o comisión canalizado a través de una empresa
fantasma, o ventas simuladas para inflar las cifras. La autoridad fiscal
de México, el SAT, publica una lista negra de empresas que emiten
facturas falsas bajo el Artículo 69-B, pero para cuando un proveedor
aparece en ella, la empresa ya ha deducido esos gastos y queda como
responsable. Las herramientas actuales marcan elementos extraños de uno
en uno y dejan que una persona los conecte. Nadie sigue el dinero hasta
el final, nadie construye las pruebas, y los proveedores honestos que
simplemente parecen sospechosos también terminan siendo acusados.

# El gran desafío

Dada la contabilidad de una empresa y solo la pista de que algo anda
mal, ¿puede un agente de IA encontrar el fraude, seguir el dinero y
probarlo, sin acusar a nadie a quien no pueda respaldar?

# Posibles enfoques

1.  Investigar paso a paso: a partir de una hipótesis, buscar en el
    libro mayor, las facturas y los registros bancarios, seguir una
    pista y cambiar de rumbo cuando llegue a un callejón sin salida.
2.  Utilizar detectores simples (proveedores en listas negras, pagos que
    no coinciden con las facturas, dinero que se mueve en círculo) para
    orientar al agente hacia lo que vale la pena profundizar.
3.  Construir un rastreo de evidencia para cada acusación y negarse a
    nombrar a un proveedor que no pueda respaldar con una regla clara
    infringida y un monto en pesos.

# Recursos para hackers

Los equipos construyen sobre recursos reales y gratuitos que existen en
línea. El SAT publica la lista oficial del Artículo 69-B de empresas que
emiten facturas falsas (EFOS), un conjunto de datos mexicano real y
descargable, junto con los esquemas de facturación CFDI 4.0. IBM AMLSim
(de código abierto) genera las redes de flujo de dinero y los patrones
de empresas fantasma detrás de moches y operaciones circulares
(round-tripping). Los conjuntos de datos públicos sobre fraude
financiero, como el de IEEE-CIS en Kaggle, brindan líneas base para las
verificaciones de anomalías. Los equipos arman el estado de datos de una
empresa a partir de estas piezas (un libro mayor, facturas, registros
bancarios y una lista de proveedores) y luego construyen el ciclo de
investigación.

**Nota sobre las herramientas:** esta categoría realiza muchas llamadas
a la IA por investigación, por lo que un modelo local (Ollama) con
almacenamiento en caché es más seguro que usar únicamente el nivel
gratuito de Gemini, el cual puede alcanzar sus límites diarios.

# Qué construir

Un agente forense que investigue registros que nunca ha visto y entregue
un expediente de caso: el esquema, los proveedores involucrados, el
rastreo de evidencia y el monto en pesos, más una lista corta de pistas
que decidió no seguir y el motivo. Entregar código funcional y una
demostración en vivo de 3 minutos donde los jueces oculten un nuevo
esquema en los datos, el agente rastree el dinero en pantalla y luego
responda una pregunta sorpresa sobre su razonamiento.

# Por qué importa

Cada peso perdido en facturas falsas se le quita a un negocio honesto y
al erario público, y cada proveedor acusado erróneamente pierde un
cliente sin motivo. Un agente que investiga y prueba, en lugar de solo
marcar, marca la diferencia entre un informe que se desmorona y un caso
sobre el cual una empresa puede tomar medidas. Este es el trabajo
forense que Infosys realiza a escala, y probar antes de acusar es lo que
separa a un auditor real de alguien que solo adivina.

# Criterios de evaluación

-   **Resultados:** en registros que nunca ha visto, ¿cuánto fraude
    oculto encuentra y prueba correctamente el agente?
-   **Juicio:** ¿se niega a acusar a proveedores a los que no pueda
    respaldar y puede defender un hallazgo cuando un juez lo cuestione?
-   **Factibilidad:** ¿podría un equipo real de finanzas o auditoría
    confiar en esto y utilizarlo?
-   **Claridad:** ¿el expediente del caso es fácil de seguir, con un
    rastreo de dinero claro?
