# Azure Resource Scale Validator (CLI) - New

Simple Python CLI to:
1. Read expected Azure resources from CSV
2. Authenticate with Azure CLI using Device Auth
3. Query Azure Resource Graph
4. Compare expected vs actual configuration by resource name and configuration
5. Export comparison report to CSV
6. Generate AI mismatch explanation using GitHub Copilot SDK

## Input CSV format

The input file must contain these headers:
- `S.No`
- `Azure Resource Type`
- `Azure Resource Name`
- `Configuration`

## Supported resource type labels (current mapping)

- `Azure VM Machine` -> `microsoft.compute/virtualmachines` (compares VM size)
- `Azure SQL DataBase` -> `microsoft.sql/servers/databases` (compares SQL sku/objective)
- `Azure AppService Plan` -> `microsoft.web/serverfarms` (compares SKU)

## Prerequisites

- Python 3.10+
- Azure CLI installed and available as `az`
- Azure CLI extension `resource-graph` installed:
  ```powershell
  az extension add --name resource-graph
  ```
- GitHub Copilot CLI available on `PATH` (or pass `--copilot-cli-path`)

## Setup

```powershell
cd c:\Users\anbonagi\Downloads\AzureResValidator
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
```

### Configure Environment Variables

1. Copy the example environment file:
   ```powershell
   Copy-Item .env.example .env
   ```

2. Edit `.env` and set your Azure credentials:
   ```
   AZURE_SUBSCRIPTION_ID=your-subscription-id-here
   AZURE_RESOURCE_GROUP=your-resource-group-name-here
   ```

The `.env` file is automatically loaded when you run the tool.

**⚠️ Security Note:** Never commit `.env` files to version control. The `.gitignore` file is configured to exclude it.

## Run

### Option 1: Using .env file (recommended)

After configuring your `.env` file (see Setup section), simply run:

```powershell
python -m azure_res_validator
```

The CLI will:
- Automatically load Azure credentials from `.env`
- Read input CSV from `input/*.csv` (first CSV found)
- Write output to `output/azure_scale_validation_output.csv`

### Option 2: Using environment variables

Set environment variables and run with defaults:

```powershell
$env:AZURE_SUBSCRIPTION_ID = "c4c0f76f-7de8-41ee-9667-ee121e33208e"
$env:AZURE_RESOURCE_GROUP = "rg-image-to-report"

python -m azure_res_validator
```

### Option 3: Explicit command-line arguments

```powershell
python -m azure_res_validator `
  --input input/Expected_AzureScale.csv `
  --subscription-id c4c0f76f-7de8-41ee-9667-ee121e33208e `
  --resource-group rg-image-to-report `
  --output output/report.csv
```

### Option 4: Mix .env file and CLI args

CLI args override .env variables:

```powershell
python -m azure_res_validator `
  --input custom-input.csv `
  --output custom-output.csv
```

### With explicit Copilot options:

```powershell
python -m azure_res_validator `
  --ai-provider copilot-sdk `
  --ai-model gpt-5 `
  --github-token <GITHUB_TOKEN>
```

## Environment Variables

The CLI loads environment variables from a `.env` file in the project root (recommended) or from system environment variables. Command-line arguments take precedence over both.

Configuration priority (highest to lowest):
1. Command-line arguments
2. System environment variables
3. `.env` file

Available environment variables:

- `AZURE_SUBSCRIPTION_ID` – Azure subscription ID (required)
- `AZURE_RESOURCE_GROUP` – Azure resource group name (required)
- `AZURE_RESOURCE_GROUP` – Azure resource group name
- `AZURE_RES_INPUT_CSV` – Path to input CSV (defaults to first CSV in `input/` folder)
- `AZURE_RES_OUTPUT_CSV` – Path to output CSV (defaults to `output/azure_scale_validation_output.csv`)

## Copilot SDK integration status

This version includes live Copilot SDK integration:
- `CopilotSdkAdapter` in `src/azure_res_validator/copilot_adapter.py`
- `MockCopilotAdapter` fallback if SDK is unavailable or response fails
- CLI switch `--ai-provider copilot-sdk|mock`
