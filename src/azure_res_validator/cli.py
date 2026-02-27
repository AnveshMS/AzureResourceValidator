from __future__ import annotations

import argparse
import asyncio
import logging
import os
from pathlib import Path

from dotenv import load_dotenv

from azure_res_validator.azure_client import AzureCliError, ensure_device_login, fetch_resources
from azure_res_validator.compare import compare_resources, load_expected_resources, write_results_csv
from azure_res_validator.copilot_adapter import CopilotSdkAdapter, MockCopilotAdapter

logger = logging.getLogger(__name__)


def _get_project_root() -> Path:
    return Path(__file__).parent.parent.parent


def _get_default_input_csv() -> Path:
    input_dir = _get_project_root() / "input"
    csvs = list(input_dir.glob("*.csv"))
    if csvs:
        return csvs[0]
    return input_dir / "Expected_AzureScale.csv"


def _get_default_output_path() -> Path:
    output_dir = _get_project_root() / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir / "azure_scale_validation_output.csv"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="azure-res-validator",
        description=(
            "Validate expected Azure resource configuration from a CSV against "
            "Azure Resource Graph and generate a CSV report."
        ),
    )
    parser.add_argument(
        "--input",
        default=None,
        help="Path to expected input CSV file (defaults to input/*.csv, env: AZURE_RES_INPUT_CSV)",
    )
    parser.add_argument(
        "--subscription-id",
        default=None,
        help="Azure subscription ID (env: AZURE_SUBSCRIPTION_ID)",
    )
    parser.add_argument(
        "--resource-group",
        default=None,
        help="Azure resource group (env: AZURE_RESOURCE_GROUP)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Path of output CSV report file (defaults to output/azure_scale_validation_output.csv, env: AZURE_RES_OUTPUT_CSV)",
    )
    parser.add_argument(
        "--ai-provider",
        choices=["copilot-sdk", "mock"],
        default="copilot-sdk",
        help="AI explanation provider",
    )
    parser.add_argument(
        "--ai-model",
        default="gpt-5",
        help="Model name used by Copilot SDK",
    )
    parser.add_argument(
        "--github-token",
        default=None,
        help="Optional GitHub token for Copilot SDK auth",
    )
    parser.add_argument(
        "--copilot-cli-path",
        default=None,
        help="Optional full path to copilot CLI executable",
    )
    return parser


def _resolve_argument(arg_value: str | None, env_var: str, default_factory, arg_name: str) -> str:
    """Resolve argument with priority: CLI arg > env var > default."""
    if arg_value:
        return str(arg_value)
    env_value = os.getenv(env_var)
    if env_value:
        return env_value
    default_val = default_factory()
    if not default_val:
        raise ValueError(f"{arg_name} not provided via CLI, {env_var}, or auto-resolved default")
    return str(default_val)


def main() -> None:
    # Load environment variables from .env file
    load_dotenv()
    
    args = _build_parser().parse_args()
    
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format="[%(levelname)s] %(name)s: %(message)s",
    )

    logger.info("Starting Azure Resource Scale Validator")

    input_path = Path(
        _resolve_argument(args.input, "AZURE_RES_INPUT_CSV", _get_default_input_csv, "Input CSV")
    ).expanduser().resolve()

    subscription_id = _resolve_argument(
        args.subscription_id, "AZURE_SUBSCRIPTION_ID", lambda: None, "Subscription ID"
    )

    resource_group = _resolve_argument(
        args.resource_group, "AZURE_RESOURCE_GROUP", lambda: None, "Resource Group"
    )

    output_path = Path(
        _resolve_argument(args.output, "AZURE_RES_OUTPUT_CSV", _get_default_output_path, "Output CSV")
    ).expanduser().resolve()

    logger.info(f"Input CSV: {input_path}")
    logger.info(f"Output CSV: {output_path}")
    logger.info(f"Azure Subscription: {subscription_id}")
    logger.info(f"Azure Resource Group: {resource_group}")

    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    logger.info("Authenticating with Azure CLI...")
    ensure_device_login()
    logger.info("Azure authentication successful")

    logger.info("Loading expected resources from CSV...")
    expected_resources = load_expected_resources(input_path)
    logger.info(f"Loaded {len(expected_resources)} expected resources")

    logger.info("Querying Azure Resource Graph...")
    try:
        actual_resources = fetch_resources(
            subscription_id=subscription_id,
            resource_group=resource_group,
        )
    except AzureCliError as exc:
        logger.error(f"Azure Resource Graph query failed: {exc}")
        raise SystemExit(str(exc)) from exc
    logger.info(f"Found {len(actual_resources)} resources in Azure Resource Graph")

    logger.info(f"Initializing AI provider: {args.ai_provider}")
    if args.ai_provider == "copilot-sdk":
        logger.info(f"Using Copilot SDK with model: {args.ai_model}")
        if args.github_token:
            logger.info("GitHub token provided for authentication")
        else:
            logger.info("Using device authentication (will prompt if needed)")
        
        # Create event loop for Copilot SDK operations
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        adapter = CopilotSdkAdapter(
            model=args.ai_model,
            github_token=args.github_token,
            copilot_cli_path=args.copilot_cli_path,
        )
        adapter.set_event_loop(loop)
        
        # Initialize Copilot SDK adapter
        logger.info("Initializing Copilot SDK resources...")
        try:
            loop.run_until_complete(adapter.initialize())
        except Exception as e:
            logger.error(f"Failed to initialize Copilot SDK: {e}")
            adapter = MockCopilotAdapter()
            logger.info("Falling back to mock AI provider")
            loop = None
    else:
        logger.info("Using mock AI provider (no external API calls)")
        adapter = MockCopilotAdapter()
        loop = None

    logger.info("Comparing resources and generating explanations...")
    results = compare_resources(
        expected_resources=expected_resources,
        actual_by_name=actual_resources,
        copilot_adapter=adapter,
    )
    
    # Cleanup adapter resources
    logger.info("Cleaning up AI adapter resources...")
    if isinstance(adapter, CopilotSdkAdapter) and loop:
        try:
            loop.run_until_complete(adapter.cleanup())
        finally:
            loop.close()
    else:
        asyncio.run(adapter.cleanup())
    
    logger.info(f"Writing results to CSV: {output_path}")
    write_results_csv(results=results, output_path=output_path)

    mismatch_count = sum(1 for row in results if row.match_status == "MISMATCH")
    match_count = sum(1 for row in results if row.match_status == "MATCH")
    logger.info(f"Validation complete. Total: {len(results)}, Matches: {match_count}, Mismatches: {mismatch_count}")
    print(
        f"Validation complete. Total: {len(results)}, "
        f"Matches: {match_count}, Mismatches: {mismatch_count}, Output: {output_path}"
    )


if __name__ == "__main__":
    main()
