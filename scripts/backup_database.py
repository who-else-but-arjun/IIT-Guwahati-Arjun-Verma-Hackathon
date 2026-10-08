"""Refresh the portable MongoDB first-run snapshot from the running Compose stack."""

from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "seed" / "financial_nlp.archive.gz"


def main() -> None:
    result = subprocess.run(
        [
            "docker", "compose", "exec", "-T", "mongo", "mongodump",
            "--db", "financial_nlp", "--archive", "--gzip",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_bytes(result.stdout)
    print(f"Saved MongoDB seed snapshot to {OUTPUT} ({len(result.stdout):,} bytes).")


if __name__ == "__main__":
    main()
