import hashlib
import json

import pytest

from boa.config.paths import PathConfig
from boa.config import physical_parameters, run_manifest
from boa.model.bisection import SearchParams


def _cfg(tmp_path, **kw):
    cfg = PathConfig.from_root(tmp_path, **kw)
    cfg.costs_dir.mkdir(parents=True, exist_ok=True)
    cfg.input_data_path.write_bytes(b"xlsx-v1")
    return cfg


def test_creates_then_appends(tmp_path):
    cfg = _cfg(tmp_path, input_set="cds", cost_set="c1")
    m1 = run_manifest.record_invocation(cfg, "build-cache", ["--region", "EU"])
    m2 = run_manifest.record_invocation(cfg, "query", ["--region", "EU"])
    assert m1["created_at"] == m2["created_at"]
    assert [i["command"] for i in m2["invocations"]] == ["build-cache", "query"]
    assert m2["provenance"]["cost_set"] == "c1"


def test_records_resolved_parameters(tmp_path):
    cfg = _cfg(tmp_path, input_set="cds", cost_set="c1")
    params = {"demand_mw": 1000.0, "coverage": 0.85, "p": 15, "samples": 1000, "years": [2025, 2026]}
    m = run_manifest.record_invocation(cfg, "run", [], parameters=params)
    assert m["invocations"][-1]["parameters"] == params


def test_provenance_records_full_search_params(tmp_path):
    cfg = _cfg(tmp_path, input_set="cds", cost_set="c1")
    m = run_manifest.record_invocation(cfg, "run", [])
    assert m["provenance"]["search_params"] == SearchParams().as_dict()
    assert m["provenance"]["lifetimes"] == physical_parameters.LIFETIMES


def test_non_scenario_params_hash_is_stable_and_forks_on_change(tmp_path):
    import dataclasses

    base = run_manifest.non_scenario_params_hash(SearchParams())
    assert base == run_manifest.non_scenario_params_hash(SearchParams())
    assert len(base) == 4

    changed = dataclasses.replace(SearchParams(), ladder_rungs=SearchParams().ladder_rungs + 1)
    assert run_manifest.non_scenario_params_hash(changed) != base


def test_a_default_run_keeps_the_hash_of_its_other_parameters_alone():
    """A key for an option left off, even one holding `None`, would rename every existing default run folder."""
    payload = {"lifetimes": physical_parameters.LIFETIMES, "search_params": SearchParams().as_dict()}
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:4]
    assert run_manifest.non_scenario_params_hash(SearchParams()) == digest


def test_exact_designs_fork_the_run_hash_and_provenance_only_when_set(tmp_path):
    base = run_manifest.non_scenario_params_hash(SearchParams())
    assert run_manifest.non_scenario_params_hash(SearchParams(), exact=False) == base
    assert run_manifest.non_scenario_params_hash(SearchParams(), exact=True) != base

    cfg = _cfg(tmp_path, input_set="cds", cost_set="c1")
    assert "exact" not in run_manifest.provenance(cfg)
    assert run_manifest.provenance(cfg, exact=True)["exact"] is True


@pytest.mark.parametrize("option", [{"exact": True}, {"min_load": 0.3}])
def test_the_manifest_records_the_run_hash_with_each_option(tmp_path, option):
    cfg = _cfg(tmp_path, input_set="cds", cost_set="c1")
    manifest = run_manifest.record_invocation(cfg, "run", [], **option)
    assert manifest["non_scenario_params_hash"] == run_manifest.non_scenario_params_hash(SearchParams(), **option)


@pytest.mark.parametrize("first", [False, True])
def test_a_run_refuses_to_mix_exact_and_default_designs_either_way(tmp_path, first):
    cfg = _cfg(tmp_path, input_set="cds", cost_set="c1", run="shared")
    run_manifest.record_invocation(cfg, "query", [], exact=first)
    with pytest.raises(RuntimeError, match="exact"):
        run_manifest.record_invocation(cfg, "query", [], exact=not first)


def test_a_minimum_load_forks_the_run_hash_and_provenance_only_when_set(tmp_path):
    base = run_manifest.non_scenario_params_hash(SearchParams())
    assert run_manifest.non_scenario_params_hash(SearchParams(), min_load=None) == base
    loaded = run_manifest.non_scenario_params_hash(SearchParams(), min_load=0.3)
    assert loaded not in (base, run_manifest.non_scenario_params_hash(SearchParams(), exact=True))
    # A minimum load turns exact designs on, so the flag changes nothing on top of it.
    assert run_manifest.non_scenario_params_hash(SearchParams(), exact=True, min_load=0.3) == loaded
    assert run_manifest.non_scenario_params_hash(SearchParams(), min_load=0.2) != loaded

    cfg = _cfg(tmp_path, input_set="cds", cost_set="c1")
    assert "min_load" not in run_manifest.provenance(cfg)
    assert run_manifest.provenance(cfg, min_load=0.3)["min_load"] == 0.3


@pytest.mark.parametrize("first, second", [(None, 0.3), (0.3, None), (0.3, 0.2)])
def test_a_run_refuses_to_mix_minimum_loads(tmp_path, first, second):
    cfg = _cfg(tmp_path, input_set="cds", cost_set="c1", run="shared")
    run_manifest.record_invocation(cfg, "query", [], min_load=first)
    with pytest.raises(RuntimeError, match="min_load"):
        run_manifest.record_invocation(cfg, "query", [], min_load=second)


def test_a_minimum_load_records_exact_designs_with_or_without_the_flag(tmp_path):
    """`boa-run --min-load 0.3` and `boa-run query --min-load 0.3 --exact-designs` share a run folder."""
    cfg = _cfg(tmp_path, input_set="cds", cost_set="c1", run="shared")
    run_manifest.record_invocation(cfg, "run", [], min_load=0.3)
    manifest = run_manifest.record_invocation(cfg, "query", [], exact=True, min_load=0.3)
    assert manifest["provenance"]["exact"] is True


def test_record_invocation_stores_description_hash_only_at_creation(tmp_path):
    cfg = _cfg(tmp_path, input_set="cds", cost_set="c1")
    m1 = run_manifest.record_invocation(cfg, "run", [])
    expected_hash = run_manifest.non_scenario_params_hash(SearchParams())
    assert m1["non_scenario_params_hash"] == expected_hash

    m2 = run_manifest.record_invocation(cfg, "query", [])
    assert m2["non_scenario_params_hash"] == expected_hash


def test_refuses_mixed_provenance(tmp_path):
    cfg = _cfg(tmp_path, input_set="cds", cost_set="c1", run="shared")
    run_manifest.record_invocation(cfg, "query", [])
    cfg.input_data_path.write_bytes(b"xlsx-v2")
    with pytest.raises(RuntimeError, match="input_data_sha256"):
        run_manifest.record_invocation(cfg, "query", [])


def test_v1_manifest_is_refused_rather_than_compared(tmp_path):
    """
    `provenance` gained `availability_signature`, which a schema-1 manifest cannot have.
    Comparing field by field would report a spurious difference on every key that moved,
    so a stale-schema manifest is refused with an actionable message instead.
    """
    path_config = _cfg(tmp_path, input_set="cds", cost_set="c1", run="legacy")
    path_config.run_dir.mkdir(parents=True, exist_ok=True)
    path_config.run_manifest_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "run": "legacy",
                "created_at": "2025-01-01T00:00:00+00:00",
                "provenance": {"input_set": path_config.input_set, "cost_set": path_config.cost_set},
                "invocations": [],
            }
        )
    )

    with pytest.raises(RuntimeError, match="new --run"):
        run_manifest.record_invocation(path_config, "boa-run", [])
