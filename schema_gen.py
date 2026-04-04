"""Generate combined JSON Schema from Pydantic models.

Usage: python schema_gen.py <module>

Reads the SCHEMA_MODELS list from the given module and writes a
combined JSON Schema to stdout.  The .pth file in the venv ensures
both models_poller and models_remote_client are importable.
"""

import importlib
import json
import sys

from pydantic import BaseModel


def generate_schema(models: list[type[BaseModel]]) -> None:
    """Merge JSON Schemas for *models* and write to stdout."""
    schemas = [m.model_json_schema() for m in models]

    defs: dict[str, object] = {}
    refs: list[dict[str, str]] = []
    for model, s in zip(models, schemas, strict=True):
        defs.update(s.get("$defs", {}))
        name = model.__name__
        defs[name] = {k: v for k, v in s.items() if k != "$defs"}
        refs.append({"$ref": f"#/$defs/{name}"})

    schema: dict[str, object] = {"$defs": defs, "anyOf": refs}
    _strip_titles(schema)

    json.dump(schema, sys.stdout, indent=2)
    sys.stdout.write("\n")


def _strip_titles(obj: object) -> None:
    """Remove per-property 'title' keys so json-schema-to-typescript
    inlines primitive types instead of emitting named aliases."""
    if isinstance(obj, dict):
        for key, val in list(obj.items()):
            if key == "properties" and isinstance(val, dict):
                for prop in val.values():
                    if isinstance(prop, dict):
                        prop.pop("title", None)
            _strip_titles(val)
    elif isinstance(obj, list):
        for item in obj:
            _strip_titles(item)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <module>", file=sys.stderr)
        sys.exit(1)

    mod = importlib.import_module(sys.argv[1])
    generate_schema(mod.SCHEMA_MODELS)
