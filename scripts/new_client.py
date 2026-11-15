"""Create a clean independent project; never copy databases, secrets or Git history."""

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from store_config import validate

ROOT = Path(__file__).resolve().parents[1]


def scaffold(configuration, destination):
    config = validate(configuration)
    target = Path(destination).resolve()
    if target.exists() or target == ROOT or ROOT in target.parents:
        raise ValueError("Choose a new directory outside the starter project.")

    def ignore(directory, names):
        return [
            name
            for name in names
            if name
            in [
                ".git",
                ".venv",
                "data",
                "artifacts",
                "__pycache__",
                ".pytest_cache",
                "examples",
            ]
            or name.startswith(".env")
            and name != ".env.example"
        ]

    shutil.copytree(ROOT, target, ignore=ignore)
    (target / "profiles/default.json").write_text(json.dumps(config, indent=2) + "\n")
    (target / "README.md").write_text(
        "# "
        + config["businessName"]
        + "\n\nIndependent client project generated from Growthly E-commerce Starter. Public configuration is in `profiles/default.json`. No accounts, customer data, database credentials or storage secrets were copied.\n\n## Local preview\n\n```bash\npython -m venv .venv\n.venv/bin/pip install -r requirements-dev.txt\nPREVIEW=1 .venv/bin/python app.py seed\n.venv/bin/python app.py\n```\n\nOpen http://localhost:3000. Demo products are hidden in production. Configure approved contacts and payment methods before checkout.\n\nFor production provisioning and security checks, follow [CLIENT_SETUP.md](CLIENT_SETUP.md). See [ARCHITECTURE.md](ARCHITECTURE.md), [CUSTOMIZATION.md](CUSTOMIZATION.md) and [TEST_REPORT.md](TEST_REPORT.md). Source-starter test results are not proof that this client has been deployed or verified live. Run the tests again after customization.\n"
    )
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    target = scaffold(json.loads(Path(args.config).read_text()), args.output)
    print("Created independent project:", target)
    print(
        "Create new database, storage credentials, session secret and admin invitation. No secrets or data were copied."
    )
