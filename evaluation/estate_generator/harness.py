"""Private fixture rendering, canonicalization, and sidecar serialization."""

from __future__ import annotations

import json
import re
from dataclasses import replace
from pathlib import Path
from random import Random

from app.estate_generator.config import EstateGeneratorConfig, ObservationProfile
from app.estate_generator.exporter import export_sqlite
from app.estate_generator.models import BankTransaction, GeneratedEstate
from app.estate_generator.output import export_csv
from evaluation.estate_generator.scenarios import PrivateDecoy, PrivateScenario, ScenarioRun


def render_fixture(
    run: ScenarioRun,
    config: EstateGeneratorConfig,
    output_path: Path,
    *,
    overwrite: bool = False,
    sidecar_stem: str | None = None,
) -> tuple[Path, Path, Path]:
    """Write the public estate and private sibling truth/provenance sidecars."""
    if output_path.exists() and not overwrite:
        raise FileExistsError(f"refusing to overwrite existing estate: {output_path}")
    scenario_evidence = _prepare_fixture(run, config)
    export_sqlite(
        run.estate, output_path, observation_profile=config.observation_profile, overwrite=overwrite
    )
    truth_path, provenance_path = _write_sidecars(
        run,
        config,
        output_path.parent,
        scenario_evidence,
        stem=sidecar_stem or output_path.stem,
        overwrite=overwrite,
    )
    return output_path, truth_path, provenance_path


def render_fixture_run(
    run: ScenarioRun,
    config: EstateGeneratorConfig,
    run_directory: Path,
    *,
    sqlite_only: bool = False,
    overwrite: bool = False,
) -> tuple[Path, Path, Path]:
    """Write a timestamped run directory as CSVs or one SQLite database."""
    if sqlite_only:
        return render_fixture(
            run,
            config,
            run_directory / "estate.db",
            overwrite=overwrite,
            sidecar_stem=run_directory.name,
        )
    run_directory.mkdir(parents=True, exist_ok=True)
    scenario_evidence = _prepare_fixture(run, config)
    export_csv(
        run.estate,
        run_directory,
        observation_profile=config.observation_profile,
        overwrite=overwrite,
    )
    truth_path, provenance_path = _write_sidecars(
        run,
        config,
        run_directory,
        scenario_evidence,
        stem=run_directory.name,
        overwrite=overwrite,
    )
    return run_directory, truth_path, provenance_path


def _prepare_fixture(
    run: ScenarioRun, config: EstateGeneratorConfig
) -> dict[str, dict[str, list[str]]]:
    visible_transactions = {item.txn_id for item in _observed_transactions(run.estate, config)}
    invoice_map, transaction_map = canonicalize_public_records(run.estate, config.seed)
    scenario_evidence = {
        item.scheme_id: {
            "visible_invoice_ids": [invoice_map[value] for value in item.invoices],
            "visible_transaction_ids": [
                transaction_map[value]
                for value in item.transactions
                if value in visible_transactions
            ],
            "hidden_transaction_ids": [
                transaction_map[value]
                for value in item.transactions
                if value not in visible_transactions
            ],
        }
        for item in run.scenarios
    }
    run.scenarios[:] = [
        _remap_scenario(item, invoice_map, transaction_map, visible_transactions)
        for item in run.scenarios
    ]
    run.decoys[:] = [_remap_decoy(item, invoice_map) for item in run.decoys]
    return scenario_evidence


def _write_sidecars(
    run: ScenarioRun,
    config: EstateGeneratorConfig,
    public_directory: Path,
    scenario_evidence: dict[str, dict[str, list[str]]],
    *,
    stem: str,
    overwrite: bool,
) -> tuple[Path, Path]:
    private_directory = public_directory / "private"
    truth_path = private_directory / f"{stem}.ground_truth.json"
    provenance_path = private_directory / f"{stem}.provenance.json"
    if not overwrite and (truth_path.exists() or provenance_path.exists()):
        raise FileExistsError("refusing to overwrite existing private fixture sidecar")
    private_directory.mkdir(parents=True, exist_ok=True)
    truth_path.write_text(
        json.dumps(truth_document(run, config), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    provenance_path.write_text(
        json.dumps(provenance_document(run, config, scenario_evidence), indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    return truth_path, provenance_path


def canonicalize_public_records(
    estate: GeneratedEstate, seed: int
) -> tuple[dict[str, str], dict[str, str]]:
    """Seed-shuffle IDs and row order, preserving every public link.

    This runs after scenarios are composed so scenario rows cannot be identified
    by append-only identifiers or final insertion positions.
    """
    random = Random(seed ^ 0xC0FFEE)
    invoice_map = _id_map([item.uuid for item in estate.invoices], "INV", random)
    transaction_map = _id_map([item.txn_id for item in estate.bank_transactions], "BNK", random)
    po_map = _id_map([item.po_id for item in estate.purchase_orders], "PO", random)
    contract_map = _id_map([item.contract_id for item in estate.contracts], "CTR", random)
    estate.invoices = _shuffled(
        [replace(item, uuid=invoice_map[item.uuid]) for item in estate.invoices], random
    )
    estate.purchase_orders = _shuffled(
        [replace(item, po_id=po_map[item.po_id]) for item in estate.purchase_orders], random
    )
    estate.contracts = _shuffled(
        [replace(item, contract_id=contract_map[item.contract_id]) for item in estate.contracts],
        random,
    )
    estate.vendors = _shuffled(list(estate.vendors), random)
    estate.employees = _shuffled(list(estate.employees), random)
    estate.efos_records = _shuffled(list(estate.efos_records), random)
    estate.purchase_order_contracts = {
        po_map[key]: contract_map[value] for key, value in estate.purchase_order_contracts.items()
    }
    estate.payable_balances = {
        invoice_map[key]: value for key, value in estate.payable_balances.items()
    }
    estate.receivable_balances = {
        invoice_map[key]: value for key, value in estate.receivable_balances.items()
    }
    estate.cancellation_reversals = {
        invoice_map[key]: value for key, value in estate.cancellation_reversals.items()
    }
    estate.ledger = _shuffled(
        [
            replace(
                item,
                invoice_uuid=(
                    invoice_map[item.invoice_uuid] if item.invoice_uuid is not None else None
                ),
                description=_remap_text(item.description, invoice_map),
            )
            for item in estate.ledger
        ],
        random,
    )
    estate.ledger = [
        replace(item, entry_id=index) for index, item in enumerate(estate.ledger, start=1)
    ]
    estate.bank_transactions = _shuffled(
        [
            replace(
                item,
                txn_id=transaction_map[item.txn_id],
                reference=_remap_text(item.reference, invoice_map),
            )
            for item in estate.bank_transactions
        ],
        random,
    )
    return invoice_map, transaction_map


def truth_document(run: ScenarioRun, config: EstateGeneratorConfig) -> dict[str, object]:
    return {
        "seed": config.seed,
        "company_rfc": run.estate.company_rfc,
        "schemes": [
            {
                "scheme_id": item.scheme_id,
                "type": item.scheme_type,
                "entities": list(item.entities),
                "supporting_invoices": list(item.invoices),
                "supporting_txns": list(item.transactions),
                "peso_amount": item.peso_centavos / 100,
                "difficulty": item.difficulty,
                "expected_published_finding": not (
                    config.observation_profile is ObservationProfile.COMPANY_ONLY
                    and item.scheme_type == "round_tripping"
                ),
            }
            for item in run.scenarios
        ],
        "decoys": [
            {
                "entity": item.entity,
                "signal": item.signal,
                "why_innocent": item.why_innocent,
                "invoices": list(item.invoices),
            }
            for item in run.decoys
        ],
    }


def provenance_document(
    run: ScenarioRun,
    config: EstateGeneratorConfig,
    scenario_evidence: dict[str, dict[str, list[str]]],
) -> dict[str, object]:
    return {
        "observation_profile": config.observation_profile.value,
        "observation_note": _observation_note(config.observation_profile),
        "scenarios": [
            {
                "scheme_id": item.scheme_id,
                "maximum_public_confidence": item.maximum_public_confidence,
                "public_peso_amount": item.peso_centavos / 100,
                "amount_basis": _amount_basis(item.scheme_type, config.observation_profile),
                "illicit_benefit": (
                    item.illicit_benefit_centavos / 100
                    if item.illicit_benefit_centavos is not None
                    else None
                ),
                **scenario_evidence[item.scheme_id],
            }
            for item in run.scenarios
        ],
        "decoys": [
            {
                "entity": item.entity,
                "public_explanation": item.why_innocent,
                "public_invoice_ids": list(item.invoices),
            }
            for item in run.decoys
        ],
    }


def _amount_basis(scheme_type: str, profile: ObservationProfile) -> str:
    if scheme_type == "kickback":
        if profile is ObservationProfile.COMPANY_ONLY:
            return "invoice exposure where a vendor account equals the approver account"
        return "illicit benefit visible in the vendor-to-employee return transfer"
    return {
        "phantom_vendor": "gross unsupported paid invoice exposure",
        "round_tripping": "principal paid from the company, not cycle volume",
        "threshold_splitting": "aggregate gross value of the linked consolidated obligation",
        "revenue_inflation": "gross cancelled invoices left unreversed",
    }[scheme_type]


def _observation_note(profile: ObservationProfile) -> str:
    if profile is ObservationProfile.COMPANY_ONLY:
        return (
            "company_only hides transfers with no company account endpoint; "
            "those cases are probable at most."
        )
    return (
        "challenge_wide includes the configured counterparty transfers "
        "needed for complete evidence."
    )


def _observed_transactions(
    estate: GeneratedEstate, config: EstateGeneratorConfig
) -> list[BankTransaction]:
    if config.observation_profile is ObservationProfile.CHALLENGE_WIDE:
        return estate.bank_transactions
    return [
        item
        for item in estate.bank_transactions
        if estate.company_clabe in {item.from_clabe, item.to_clabe}
    ]


def _id_map(ids: list[str], prefix: str, random: Random) -> dict[str, str]:
    shuffled = list(ids)
    random.shuffle(shuffled)
    return {old: f"{prefix}-{index:05d}" for index, old in enumerate(shuffled, start=1)}


def _shuffled[T](items: list[T], random: Random) -> list[T]:
    random.shuffle(items)
    return items


def _remap_text(value: str, mapping: dict[str, str]) -> str:
    return re.sub(r"INV-\d{5}", lambda match: mapping.get(match.group(), match.group()), value)


def _remap_scenario(
    item: PrivateScenario,
    invoice_map: dict[str, str],
    transaction_map: dict[str, str],
    visible_transactions: set[str],
) -> PrivateScenario:
    return replace(
        item,
        invoices=tuple(invoice_map[value] for value in item.invoices),
        transactions=tuple(
            transaction_map[value] for value in item.transactions if value in visible_transactions
        ),
    )


def _remap_decoy(item: PrivateDecoy, invoice_map: dict[str, str]) -> PrivateDecoy:
    return replace(item, invoices=tuple(invoice_map[value] for value in item.invoices))
