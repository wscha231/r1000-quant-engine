#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class _DummyEstimator:
    def __init__(self, *args, **kwargs) -> None:
        pass


sklearn = types.ModuleType("sklearn")
linear_model = types.ModuleType("sklearn.linear_model")
linear_model.LogisticRegression = _DummyEstimator
linear_model.Ridge = _DummyEstimator
preprocessing = types.ModuleType("sklearn.preprocessing")
preprocessing.StandardScaler = _DummyEstimator
sys.modules.setdefault("sklearn", sklearn)
sys.modules.setdefault("sklearn.linear_model", linear_model)
sys.modules.setdefault("sklearn.preprocessing", preprocessing)

from r1000_pipeline import choose_catboost_task_type  # noqa: E402


def main() -> int:
    old = os.environ.get("R1000_CATBOOST_TASK_TYPE")
    try:
        os.environ.pop("R1000_CATBOOST_TASK_TYPE", None)
        assert choose_catboost_task_type() == "CPU"

        os.environ["R1000_CATBOOST_TASK_TYPE"] = "CPU"
        assert choose_catboost_task_type() == "CPU"

        os.environ["R1000_CATBOOST_TASK_TYPE"] = "GPU"
        assert choose_catboost_task_type() == "GPU"

        os.environ["R1000_CATBOOST_TASK_TYPE"] = "bad-value"
        assert choose_catboost_task_type() == "CPU"

        os.environ["R1000_CATBOOST_TASK_TYPE"] = "AUTO"
        assert choose_catboost_task_type() in {"CPU", "GPU"}
    finally:
        if old is None:
            os.environ.pop("R1000_CATBOOST_TASK_TYPE", None)
        else:
            os.environ["R1000_CATBOOST_TASK_TYPE"] = old

    print("catboost_task_type_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
