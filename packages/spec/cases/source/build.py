"""
Writes each ../<name>.json from source/<name>.py's `cases`. The JSON is not in
git: every client's tests build it first (npm test in packages/typescript).
"""
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
NAMES = ["queries", "writes", "access", "watch", "listen"]


def render(name: str) -> str:
    spec = importlib.util.spec_from_file_location(f"cases_{name}", HERE / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    lines = ",\n".join(json.dumps(case, ensure_ascii=False) for case in module.cases)
    return f'{{"cases": [\n{lines}\n]}}\n'


if __name__ == "__main__":
    for name in NAMES:
        (HERE.parent / f"{name}.json").write_text(render(name), encoding="utf-8")
