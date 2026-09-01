# Runs the test suite and regenerates the Allure HTML report in one step.
# pytest (via --clean-alluredir in pyproject.toml) wipes reports/allure-results
# before writing fresh results, and this script always regenerates
# reports/allure-report from them afterward, so the report can never go stale
# relative to the last run, and old results can never pile up between runs.
#
# Usage: .\run_tests.ps1

$ErrorActionPreference = "Stop"

pytest
$testExitCode = $LASTEXITCODE

allure generate reports/allure-results -o reports/allure-report --clean

if ($testExitCode -ne 0) {
    Write-Host "Tests failed (exit code $testExitCode). Report regenerated anyway for inspection." -ForegroundColor Yellow
    exit $testExitCode
}

Write-Host "All tests passed. Report regenerated at reports/allure-report." -ForegroundColor Green
