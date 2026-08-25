Import-Module ExchangeOnlineManagement
Connect-IPPSSession -UserPrincipalName "admin@DIAx48836189.onmicrosoft.com"

$appId = "61faacaa-ffd9-42b8-a319-ddb6d1178afd"
$appName = "A365GatewayPrototype Identity"
$policyName = "A365 Gateway Prototype DLP"

$location = [ordered]@{
    Workload            = "Applications"
    Location            = $appId
    LocationDisplayName = $appName
    LocationSource      = "Entra"
    LocationType        = "Individual"
    Inclusions          = @(
        @{
            Type     = "Tenant"
            Identity = "All"
        }
    )
}

$locations = ConvertTo-Json -InputObject @($location) -Depth 10 -Compress

New-DlpCompliancePolicy `
    -Name $policyName `
    -Mode Enable `
    -Locations $locations `
    -EnforcementPlanes @("Application")

New-DlpComplianceRule `
    -Name "Block credit cards in prompts" `
    -Policy $policyName `
    -ContentContainsSensitiveInformation @(
        @{ Name = "Credit Card Number"; minCount = "1" }
    ) `
    -RestrictAccess @(
        @{ setting = "UploadText"; value = "Block" }
    ) `
    -RuleErrorAction RetryThenBlock