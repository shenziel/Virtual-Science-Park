"""Regenerate contracts/*.json from contracts/models.py.

    python -m contracts.export_schemas
"""

import json
from pathlib import Path

from contracts.models import SCHEMAS

HERE = Path(__file__).parent


def render(name: str) -> str:
    schema = SCHEMAS[name].model_json_schema()
    schema = {"$schema": "https://json-schema.org/draft/2020-12/schema", "$id": f"{name}.json", **schema}
    return json.dumps(schema, indent=2, ensure_ascii=False) + "\n"


def main() -> None:
    for name in SCHEMAS:
        (HERE / f"{name}.json").write_text(render(name), encoding="utf-8")
        print(f"wrote contracts/{name}.json")


if __name__ == "__main__":
    main()
