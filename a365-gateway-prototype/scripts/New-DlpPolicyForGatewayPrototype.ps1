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
        @{ Name = "Credit Card Number"; minCount = "1" },
        @{ Name = "[KT-개인정보] 여권번호"; minCount = "1" },
        @{ Name = "[KT-개인정보] 전화번호"; minCount = "1"},
        @{ Name = "[KT-개인정보] 주민등록번호"; minCount = "1" },
        @{ Name = "South Korea Driver's License Number"; minCount = "1" },
        @{ Name = "South Korea Passport Number"; minCount = "1" },
        @{ Name = "South Korea Resident Registration Number"; minCount = "1" }
    ) `
    -RestrictAccess @(
        @{ setting = "UploadText"; value = "Block" }
    ) `
    -ReportSeverityLevel High `
    -RuleErrorAction RetryThenBlock