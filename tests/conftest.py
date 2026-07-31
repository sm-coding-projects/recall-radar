from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def load_json(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def fda_food():
    return load_json("fda_food.json")


@pytest.fixture
def cpsc_records():
    return load_json("cpsc.json")


@pytest.fixture
def fsis_records():
    return load_json("fsis.json")


@pytest.fixture
def nhtsa_lines():
    return (FIXTURES / "nhtsa_flat.tsv").read_text(encoding="latin-1").splitlines()
