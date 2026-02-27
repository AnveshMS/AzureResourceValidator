from __future__ import annotations

import csv
import logging
from pathlib import Path

from azure_res_validator.azure_client import RESOURCE_TYPE_TO_ARM
from azure_res_validator.copilot_adapter import CopilotAdapter, MismatchContext
from azure_res_validator.types import ExpectedResource, ValidationResult

logger = logging.getLogger(__name__)


def load_expected_resources(csv_path: Path) -> list[ExpectedResource]:
    resources: list[ExpectedResource] = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as infile:
        reader = csv.DictReader(infile)
        for row in reader:
            resources.append(
                ExpectedResource(
                    serial_no=(row.get("S.No") or "").strip(),
                    resource_type_label=(row.get("Azure Resource Type") or "").strip(),
                    resource_name=(row.get("Azure Resource Name") or "").strip(),
                    expected_configuration=(row.get("Configuration") or "").strip(),
                )
            )
    return resources


def _resolve_expected_arm_type(resource_type_label: str) -> str | None:
    return RESOURCE_TYPE_TO_ARM.get(resource_type_label.lower().strip())


def compare_resources(
    expected_resources: list[ExpectedResource],
    actual_by_name,
    copilot_adapter: CopilotAdapter,
) -> list[ValidationResult]:
    results: list[ValidationResult] = []

    for expected in expected_resources:
        expected_name_key = expected.resource_name.lower()
        candidates = actual_by_name.get(expected_name_key, [])
        expected_arm_type = _resolve_expected_arm_type(expected.resource_type_label)

        if not candidates:
            reason = "Resource not found in Azure Resource Graph for provided scope"
            logger.debug(f"Resource not found: {expected.resource_name} - generating AI explanation")
            ai_text = copilot_adapter.explain_mismatch(
                MismatchContext(
                    resource_name=expected.resource_name,
                    resource_type_label=expected.resource_type_label,
                    expected_configuration=expected.expected_configuration,
                    actual_configuration="NOT_FOUND",
                    mismatch_reason=reason,
                )
            )
            results.append(
                ValidationResult(
                    serial_no=expected.serial_no,
                    resource_type_label=expected.resource_type_label,
                    resource_name=expected.resource_name,
                    expected_configuration=expected.expected_configuration,
                    actual_configuration="NOT_FOUND",
                    match_status="MISMATCH",
                    mismatch_reason=reason,
                    resource_id="",
                    ai_explanation=ai_text,
                )
            )
            continue

        type_filtered = candidates
        if expected_arm_type:
            type_filtered = [c for c in candidates if c.arm_type == expected_arm_type]

        if not type_filtered:
            reason = "Name matched but Azure resource type differs"
            actual_conf = candidates[0].configuration if candidates else "UNKNOWN"
            logger.debug(f"Resource type mismatch: {expected.resource_name} (expected {expected.resource_type_label}) - generating AI explanation")
            ai_text = copilot_adapter.explain_mismatch(
                MismatchContext(
                    resource_name=expected.resource_name,
                    resource_type_label=expected.resource_type_label,
                    expected_configuration=expected.expected_configuration,
                    actual_configuration=actual_conf,
                    mismatch_reason=reason,
                )
            )
            results.append(
                ValidationResult(
                    serial_no=expected.serial_no,
                    resource_type_label=expected.resource_type_label,
                    resource_name=expected.resource_name,
                    expected_configuration=expected.expected_configuration,
                    actual_configuration=actual_conf,
                    match_status="MISMATCH",
                    mismatch_reason=reason,
                    resource_id=candidates[0].resource_id if candidates else "",
                    ai_explanation=ai_text,
                )
            )
            continue

        actual = type_filtered[0]
        is_match = (expected.expected_configuration or "").strip().lower() == (
            actual.configuration or ""
        ).strip().lower()

        if is_match:
            logger.debug(f"Resource match: {expected.resource_name} configuration matches ({actual.configuration})")
            results.append(
                ValidationResult(
                    serial_no=expected.serial_no,
                    resource_type_label=expected.resource_type_label,
                    resource_name=expected.resource_name,
                    expected_configuration=expected.expected_configuration,
                    actual_configuration=actual.configuration,
                    match_status="MATCH",
                    mismatch_reason="",
                    resource_id=actual.resource_id,
                    ai_explanation="",
                )
            )
            continue

        logger.debug(f"Configuration mismatch: {expected.resource_name} (expected {expected.expected_configuration}, got {actual.configuration}) - generating AI explanation")
        reason = "Configuration value differs"
        ai_text = copilot_adapter.explain_mismatch(
            MismatchContext(
                resource_name=expected.resource_name,
                resource_type_label=expected.resource_type_label,
                expected_configuration=expected.expected_configuration,
                actual_configuration=actual.configuration or "EMPTY",
                mismatch_reason=reason,
            )
        )
        results.append(
            ValidationResult(
                serial_no=expected.serial_no,
                resource_type_label=expected.resource_type_label,
                resource_name=expected.resource_name,
                expected_configuration=expected.expected_configuration,
                actual_configuration=actual.configuration,
                match_status="MISMATCH",
                mismatch_reason=reason,
                resource_id=actual.resource_id,
                ai_explanation=ai_text,
            )
        )

    return results


def write_results_csv(results: list[ValidationResult], output_path: Path) -> None:
    fieldnames = [
        "S.No",
        "Azure Resource Type",
        "Azure Resource Name",
        "Expected Configuration",
        "Actual Configuration",
        "Match Status",
        "Mismatch Reason",
        "Resource Id",
        "AI Mismatch Explanation",
    ]

    with output_path.open("w", encoding="utf-8", newline="") as outfile:
        writer = csv.DictWriter(outfile, fieldnames=fieldnames)
        writer.writeheader()

        for item in results:
            writer.writerow(
                {
                    "S.No": item.serial_no,
                    "Azure Resource Type": item.resource_type_label,
                    "Azure Resource Name": item.resource_name,
                    "Expected Configuration": item.expected_configuration,
                    "Actual Configuration": item.actual_configuration,
                    "Match Status": item.match_status,
                    "Mismatch Reason": item.mismatch_reason,
                    "Resource Id": item.resource_id,
                    "AI Mismatch Explanation": item.ai_explanation,
                }
            )
