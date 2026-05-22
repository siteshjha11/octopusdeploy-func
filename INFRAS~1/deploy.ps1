<#
.SYNOPSIS
    Deploys the full Octopus Deploy → Microsoft Sentinel ingestion stack.

.DESCRIPTION
    Execution order:
      1. Create / update the Log Analytics custom table  (custom-table.json)
      2. Create / update the DCE and DCR               (dcr-dce.json)
      3. Create / update the Azure Function App        (function-app.json)
      4. Assign the Monitoring Metrics Publisher role to the Function's
         managed identity on the DCR.
      5. Print DCE endpoint + DCR immutable ID for use in Function settings.

.PARAMETER ResourceGroup
    Name of the resource group to deploy into.

.PARAMETER WorkspaceName
    Log Analytics workspace name (must already exist in the same RG).

.PARAMETER WorkspaceResourceId
    Full ARM resource ID of the workspace.

.PARAMETER Location
    Azure region (defaults to resource group location).

.EXAMPLE
    .\deploy.ps1 `
        -ResourceGroup  "rg-security-prod" `
        -WorkspaceName  "law-sentinel-prod" `
        -WorkspaceResourceId "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-security-prod/providers/Microsoft.OperationalInsights/workspaces/law-sentinel-prod"
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory)][string] $ResourceGroup,
    [Parameter(Mandatory)][string] $WorkspaceName,
    [Parameter(Mandatory)][string] $WorkspaceResourceId,
    [string] $Location = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition

function Deploy-Template {
    param([string]$TemplatePath, [hashtable]$Parameters)
    Write-Host "`n[DEPLOY] $TemplatePath" -ForegroundColor Cyan
    $result = New-AzResourceGroupDeployment `
        -ResourceGroupName $ResourceGroup `
        -TemplateFile $TemplatePath `
        -TemplateParameterObject $Parameters `
        -Mode Incremental `
        -Verbose
    return $result
}

# ── 0. Ensure logged in ───────────────────────────────────────────────────────
$context = Get-AzContext
if (-not $context) {
    Write-Error "Not logged in to Azure. Run Connect-AzAccount first."
}
Write-Host "Using subscription: $($context.Subscription.Name) [$($context.Subscription.Id)]"

$params = @{ workspaceName = $WorkspaceName; workspaceResourceId = $WorkspaceResourceId }
if ($Location) { $params.location = $Location }

# ── 1. Custom table ───────────────────────────────────────────────────────────
Deploy-Template "$ScriptDir\custom-table.json" $params

# ── 2. DCE + DCR ─────────────────────────────────────────────────────────────
$dcrResult = Deploy-Template "$ScriptDir\dcr-dce.json" $params

$dceEndpoint  = $dcrResult.Outputs["dceEndpoint"].Value
$dcrImmuteId  = $dcrResult.Outputs["dcrImmutableId"].Value

Write-Host "`n✅  DCE Endpoint    : $dceEndpoint"  -ForegroundColor Green
Write-Host "✅  DCR Immutable ID: $dcrImmuteId"   -ForegroundColor Green

# ── 3. Assign Monitoring Metrics Publisher role to Function identity ──────────
Write-Host "`n[ROLE] Looking up DCR resource ID …" -ForegroundColor Cyan
$dcr = Get-AzDataCollectionRule -ResourceGroupName $ResourceGroup -RuleName "dcr-octopus-audit-events"

Write-Host "[ROLE] Assign Monitoring Metrics Publisher to Function managed identity."
Write-Host "       Run the following after your Function App is deployed and its"
Write-Host "       system-assigned identity is enabled:"
Write-Host ""
Write-Host '  $funcIdentity = (Get-AzFunctionApp -ResourceGroupName "<RG>" -Name "<FunctionAppName>").Identity.PrincipalId'
Write-Host "  New-AzRoleAssignment -ObjectId `$funcIdentity ``"
Write-Host "      -RoleDefinitionName 'Monitoring Metrics Publisher' ``"
Write-Host "      -Scope '$($dcr.Id)'"
Write-Host ""

# ── 4. Summary ────────────────────────────────────────────────────────────────
Write-Host "──────────────────────────────────────────────────────────" -ForegroundColor Yellow
Write-Host " Add these values to your Function App application settings:" -ForegroundColor Yellow
Write-Host "──────────────────────────────────────────────────────────" -ForegroundColor Yellow
Write-Host "  DCE_ENDPOINT      = $dceEndpoint"
Write-Host "  DCR_IMMUTABLE_ID  = $dcrImmuteId"
Write-Host "  DCR_STREAM_NAME   = Custom-OctopusAuditEvents_CL"
Write-Host "──────────────────────────────────────────────────────────" -ForegroundColor Yellow
