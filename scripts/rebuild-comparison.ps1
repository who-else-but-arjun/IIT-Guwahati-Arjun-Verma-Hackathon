$ErrorActionPreference = "Stop"

docker compose up -d mongo
if ($LASTEXITCODE -ne 0) {
    throw "Could not start MongoDB."
}

docker compose run --rm --no-deps `
    -e COMPARISON_STAGING_DATABASE=financial_nlp_comparison_stage `
    backend python -m scripts.rebuild_monthly_comparison
if ($LASTEXITCODE -ne 0) {
    throw "Monthly comparison replay failed; the last promoted portfolios remain available."
}
