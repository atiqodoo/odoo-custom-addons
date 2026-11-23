#Requires -RunAsAdministrator
param(
    [Parameter(Mandatory = $true)][string]$Database
)
$ErrorActionPreference = 'Stop'
$WorkspaceRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$NssmPath = Join-Path $WorkspaceRoot 'nssm-2.24\win64\nssm.exe'
$ExpectedConfig = Join-Path $WorkspaceRoot 'config\odoo-dev.conf'
$ServiceName = 'odoo-server-18.0'
$Parameters = (& $NssmPath get $ServiceName AppParameters | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or $Parameters -notlike "*$ExpectedConfig*") {
    throw 'The service does not point to the expected development configuration. No update was applied.'
}
$WasRunning = (Get-Service -Name $ServiceName).Status -eq 'Running'
try {
    if ($WasRunning) {
        Stop-Service -Name $ServiceName
        (Get-Service -Name $ServiceName).WaitForStatus('Stopped', '00:00:30')
    }
    & (Join-Path $WorkspaceRoot 'python\python.exe') (Join-Path $PSScriptRoot 'apply_update.py') --database $Database
    if ($LASTEXITCODE -ne 0) { throw 'Module update failed. See the update log and backup path printed above.' }
} finally {
    if ($WasRunning) { Start-Service -Name $ServiceName }
}
Write-Output 'Update applied. Reload each POS browser once to load the new synchronization code.'
