"""Private-fixture tests; these never run in the deployed application."""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from app.estate_generator.checks import validate_public_estate
from app.estate_generator.config import EstateGeneratorConfig, ObservationProfile
from app.estate_generator.output import create_run_directory
from evaluation.estate_generator.harness import render_fixture, render_fixture_run, truth_document
from evaluation.estate_generator.scenarios import SCHEME_TYPES, build_scenario_run


def test_all_five_fixture_has_all_types_paired_decoys_and_resolvable_truth(tmp_path: Path) -> None:
    config = EstateGeneratorConfig(seed=42, normal_event_count=30)
    run = build_scenario_run(config, all_five=True, decoy_count=5)
    output_path, truth_path, provenance_path = render_fixture(run, config, tmp_path / "estate.db")
    truth = json.loads(truth_path.read_text(encoding="utf-8"))

    assert {item["type"] for item in truth["schemes"]} == set(SCHEME_TYPES)
    assert len(truth["decoys"]) == 5
    assert provenance_path.is_file()
    with sqlite3.connect(output_path) as connection:
        invoices = {row[0] for row in connection.execute("SELECT uuid FROM invoices")}
        transactions = {row[0] for row in connection.execute("SELECT txn_id FROM bank_txns")}
    for scheme in truth["schemes"]:
        assert set(scheme["supporting_invoices"]) <= invoices
        assert set(scheme["supporting_txns"]) <= transactions
    assert truth_document(run, config)["company_rfc"] == run.estate.company_rfc
    assert all(
        len(item["supporting_txns"]) == len(set(item["supporting_txns"]))
        for item in truth["schemes"]
    )


@pytest.mark.parametrize("seed", (42, 43, 99))
def test_decoy_entities_are_never_planted_fraud_entities(seed: int) -> None:
    run = build_scenario_run(
        EstateGeneratorConfig(seed=seed, normal_event_count=30), all_five=True, decoy_count=10
    )

    scheme_entities = {entity for scenario in run.scenarios for entity in scenario.entities}
    decoy_entities = [decoy.entity for decoy in run.decoys]

    assert not scheme_entities.intersection(decoy_entities)
    assert len(decoy_entities) == len(set(decoy_entities))
    assert "cancelled_revenue" not in {decoy.signal for decoy in run.decoys}


def test_company_only_caps_counterparty_schemes_at_probable() -> None:
    config = EstateGeneratorConfig(
        seed=42,
        normal_event_count=30,
        observation_profile=ObservationProfile.COMPANY_ONLY,
    )
    run = build_scenario_run(config, all_five=True, decoy_count=0)
    confidence = {item.scheme_type: item.maximum_public_confidence for item in run.scenarios}

    assert confidence["kickback"] == "probable"
    assert confidence["round_tripping"] == "probable"
    assert confidence["phantom_vendor"] == "proven"
    kickback = next(item for item in run.scenarios if item.scheme_type == "kickback")
    vendor_rfc = next(
        entity.removeprefix("RFC:") for entity in kickback.entities if entity.startswith("RFC:")
    )
    vendor = next(item for item in run.estate.vendors if item.rfc == vendor_rfc)
    employee = next(item for item in run.estate.employees if item.emp_id in kickback.entities)
    assert vendor.bank_clabe == employee.bank_clabe
    assert not any(
        transaction.from_clabe == vendor.bank_clabe and transaction.to_clabe == employee.bank_clabe
        for transaction in run.estate.bank_transactions
    )


def test_all_five_varies_seed_order_and_large_seed_clabes_remain_valid() -> None:
    first = build_scenario_run(EstateGeneratorConfig(seed=42, normal_event_count=30), all_five=True)
    second = build_scenario_run(
        EstateGeneratorConfig(seed=43, normal_event_count=30), all_five=True
    )
    large = build_scenario_run(
        EstateGeneratorConfig(seed=99_999_999, normal_event_count=30), scheme_count=0
    )

    assert [item.scheme_type for item in first.scenarios] != [
        item.scheme_type for item in second.scenarios
    ]
    first_amounts = {item.scheme_type: item.peso_centavos for item in first.scenarios}
    second_amounts = {item.scheme_type: item.peso_centavos for item in second.scenarios}
    assert first_amounts["threshold_splitting"] != second_amounts["threshold_splitting"]
    assert first_amounts["revenue_inflation"] != second_amounts["revenue_inflation"]
    assert all(
        len(item.bank_clabe) == 18 and item.bank_clabe.isdigit() for item in large.estate.vendors
    )


def test_paid_cancelled_purchase_decoy_has_zero_net_account_effect() -> None:
    run = build_scenario_run(
        EstateGeneratorConfig(seed=42, normal_event_count=30), all_five=True, decoy_count=5
    )
    decoy = next(item for item in run.decoys if item.signal == "return_path")
    invoice_id = decoy.invoices[0]
    net_by_account: dict[str, int] = {}
    for line in run.estate.ledger:
        if line.invoice_uuid == invoice_id:
            net_by_account[line.account_code] = (
                net_by_account.get(line.account_code, 0)
                + line.debit_centavos
                - line.credit_centavos
            )

    assert net_by_account == {"5000": 0, "1180": 0, "2100": 0, "1020": 0}
    assert invoice_id in run.estate.cancellation_reversals
    transfers = [
        item for item in run.estate.bank_transactions if invoice_id in item.reference
    ]
    assert len(transfers) == 2
    assert transfers[0].amount_centavos == transfers[1].amount_centavos
    assert transfers[0].date < transfers[1].date


def test_scenario_chronology_threshold_evidence_and_efos_are_not_perfect_labels() -> None:
    run = build_scenario_run(
        EstateGeneratorConfig(seed=42, normal_event_count=30), all_five=True, decoy_count=5
    )
    validate_public_estate(run.estate)
    invoices = {item.uuid: item for item in run.estate.invoices}
    transactions = {item.txn_id: item for item in run.estate.bank_transactions}
    for scenario in run.scenarios:
        if scenario.scheme_type in {"kickback", "round_tripping"}:
            first_invoice_date = min(invoices[item].issue_date for item in scenario.invoices)
            assert all(
                transactions[item].date >= first_invoice_date for item in scenario.transactions
            )
    threshold = next(item for item in run.scenarios if item.scheme_type == "threshold_splitting")
    vendor_rfc = invoices[threshold.invoices[0]].issuer_rfc
    contracts = [item for item in run.estate.contracts if item.vendor_rfc == vendor_rfc]
    assert any("MXN 100,000" in item.scope_text for item in contracts)
    po_ids = [item.po_id for item in run.estate.purchase_orders if item.vendor_rfc == vendor_rfc]
    assert all(item in run.estate.purchase_order_contracts for item in po_ids)
    statuses = {item.status for item in run.estate.efos_records}
    presuntos = [item.rfc for item in run.estate.efos_records if item.status == "presunto"]
    assert statuses == {"presunto", "definitivo"}
    assert len(presuntos) >= 2


def test_provenance_records_visibility_amount_basis_and_decoy_evidence(tmp_path: Path) -> None:
    config = EstateGeneratorConfig(
        seed=42,
        normal_event_count=30,
        observation_profile=ObservationProfile.COMPANY_ONLY,
    )
    run = build_scenario_run(config, all_five=True, decoy_count=5)
    _, _, provenance_path = render_fixture(run, config, tmp_path / "estate.db")
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))

    assert provenance["observation_profile"] == "company_only"
    assert len(provenance["scenarios"]) == 5
    assert all(
        "amount_basis" in item and "visible_invoice_ids" in item for item in provenance["scenarios"]
    )
    assert all("public_explanation" in item for item in provenance["decoys"])
    kickback = next(
        item for item in provenance["scenarios"] if item["scheme_id"].endswith("kickback")
    )
    assert kickback["maximum_public_confidence"] == "probable"
    assert kickback["illicit_benefit"] is not None


@pytest.mark.parametrize("profile", list(ObservationProfile))
def test_kickback_expected_finding_passes_supplied_validator(
    tmp_path: Path, profile: ObservationProfile
) -> None:
    config = EstateGeneratorConfig(seed=42, normal_event_count=30, observation_profile=profile)
    run = build_scenario_run(config, all_five=True, decoy_count=0)
    output_path, truth_path, _ = render_fixture(run, config, tmp_path / "estate.db")
    kickback = next(
        item for item in json.loads(truth_path.read_text())["schemes"] if item["type"] == "kickback"
    )
    with sqlite3.connect(output_path) as connection:
        placeholders = ",".join("?" for _ in kickback["supporting_txns"])
        transaction_args = (*kickback["supporting_txns"], kickback["peso_amount"])
        transaction_id = connection.execute(
            f"SELECT txn_id FROM bank_txns WHERE txn_id IN ({placeholders}) "
            "AND ROUND(amount, 2) = ? LIMIT 1",
            transaction_args,
        ).fetchone()[0]
    submission = {
        "seed": config.seed,
        "findings": [
            {
                "scheme_type": "kickback",
                "entities": kickback["entities"],
                "rule_broken": "Conflicto de interes en la aprobacion",
                "narrative": (
                    "La cuenta bancaria del proveedor coincide con la del aprobador."
                    if profile is ObservationProfile.COMPANY_ONLY
                    else "El proveedor retorno parte del pago al aprobador."
                ),
                "peso_amount": kickback["peso_amount"],
                "confidence": "probable"
                if profile is ObservationProfile.COMPANY_ONLY
                else "proven",
                "money_trail": [
                    {
                        "from": "origen",
                        "to": "destino",
                        "amount": kickback["peso_amount"],
                        "date": "2026-01-01",
                        "exhibit_id": "EX-2",
                    }
                ],
                "exhibits": [
                    {
                        "exhibit_id": "EX-1",
                        "source_table": "invoices",
                        "record_id": kickback["supporting_invoices"][0],
                        "note": "Factura relacionada.",
                    },
                    {
                        "exhibit_id": "EX-2",
                        "source_table": "bank_txns",
                        "record_id": transaction_id,
                        "note": "Transferencia con monto conciliable.",
                    },
                    {
                        "exhibit_id": "EX-3",
                        "source_table": "vendors",
                        "record_id": kickback["entities"][0].removeprefix("RFC:"),
                        "note": "Proveedor involucrado.",
                    },
                ],
            }
        ],
        "leads_not_pursued": [],
        "run_metadata": {
            "llm_calls": 0,
            "mxn_cost": 0.0,
            "wall_clock_seconds": 0.0,
            "cost_by_role": {},
            "deterministic": True,
        },
    }
    submission_path = tmp_path / "submission.json"
    submission_path.write_text(json.dumps(submission), encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            "public/material/validate_format.py",
            "--submission",
            str(submission_path),
            "--estate",
            str(output_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_variable_mix_allows_a_zero_scheme_zero_decoy_estate() -> None:
    run = build_scenario_run(
        EstateGeneratorConfig(seed=2, normal_event_count=30), scheme_count=0, decoy_count=0
    )

    assert run.scenarios == []
    assert run.decoys == []


def test_adversarial_decoys_are_innocent_lookalikes_and_do_not_overlap_schemes() -> None:
    run = build_scenario_run(
        EstateGeneratorConfig(seed=71_001, normal_event_count=30),
        scheme_count=0,
        decoy_count=0,
        adversarial=True,
    )

    assert run.scenarios == []
    assert {item.signal for item in run.decoys} == {
        "documented_presumed_efos",
        "independent_near_threshold_orders",
        "partial_procurement_evidence_with_noisy_text",
    }
    assert len({item.entity for item in run.decoys}) == len(run.decoys)
    validate_public_estate(run.estate)


def test_explicit_scheme_selection_supports_named_subset_and_rejects_conflicts() -> None:
    config = EstateGeneratorConfig(seed=12, normal_event_count=30)
    run = build_scenario_run(
        config,
        scheme_types=("kickback", "round_tripping"),
        decoy_count=0,
    )

    assert [item.scheme_type for item in run.scenarios] == ["kickback", "round_tripping"]
    with pytest.raises(ValueError, match="unique values"):
        build_scenario_run(config, scheme_types=("kickback", "kickback"), decoy_count=0)
    with pytest.raises(ValueError, match="cannot be combined"):
        build_scenario_run(config, all_five=True, scheme_types=("kickback",), decoy_count=0)


def test_explicit_scheme_selection_run_writes_only_requested_families(tmp_path: Path) -> None:
    config = EstateGeneratorConfig(seed=12, normal_event_count=30)
    run_directory = create_run_directory(12, root=tmp_path)
    _, truth_path, _ = render_fixture_run(
        build_scenario_run(
            config,
            scheme_types=("kickback", "round_tripping"),
            decoy_count=0,
        ),
        config,
        run_directory,
    )
    truth = json.loads(truth_path.read_text(encoding="utf-8"))
    assert [item["type"] for item in truth["schemes"]] == [
        "kickback",
        "round_tripping",
    ]
    assert truth["decoys"] == []


def test_private_fixture_requires_force_for_existing_output(tmp_path: Path) -> None:
    config = EstateGeneratorConfig(seed=4, normal_event_count=30)
    output_path = tmp_path / "estate.db"
    render_fixture(build_scenario_run(config, scheme_count=1, decoy_count=1), config, output_path)

    with pytest.raises(FileExistsError):
        render_fixture(
            build_scenario_run(config, scheme_count=1, decoy_count=1), config, output_path
        )

    render_fixture(
        build_scenario_run(config, scheme_count=1, decoy_count=1),
        config,
        output_path,
        overwrite=True,
    )
