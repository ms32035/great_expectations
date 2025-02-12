from __future__ import annotations

import inspect
import logging
from unittest import mock

import pytest

from great_expectations.core.usage_statistics.events import UsageStatsEvents
from great_expectations.core.usage_statistics.usage_statistics import ENABLED_METHODS

logger = logging.getLogger(__name__)


def filter_enabled_methods(
    enabled_methods: dict[str, UsageStatsEvents]
) -> dict[str, UsageStatsEvents]:
    filtered = {}
    for qualified_method_name, event in enabled_methods.items():
        parts = qualified_method_name.split(".")
        assert (
            len(parts) == 2
        ), "ENABLED_METHODS should contain keys representing qualified method names (i.e. AbstractDataContext.add_datasource)"

        if not qualified_method_name.startswith(
            "AbstractDataContext"
        ) or qualified_method_name.endswith("__init__"):
            continue

        method_name = parts[-1]
        filtered[method_name] = event

    return filtered


@pytest.fixture
def enable_usage_stats(monkeypatch):
    monkeypatch.delenv("GE_USAGE_STATS")


@pytest.mark.unit
def test_enabled_methods_map_to_appropriate_usage_stats_events():
    assert filter_enabled_methods(ENABLED_METHODS) == {
        "add_datasource": UsageStatsEvents.DATA_CONTEXT_ADD_DATASOURCE,
        "build_data_docs": UsageStatsEvents.DATA_CONTEXT_BUILD_DATA_DOCS,
        "get_batch_list": UsageStatsEvents.DATA_CONTEXT_GET_BATCH_LIST,
        "open_data_docs": UsageStatsEvents.DATA_CONTEXT_OPEN_DATA_DOCS,
        "run_checkpoint": UsageStatsEvents.DATA_CONTEXT_RUN_CHECKPOINT,
        "run_profiler_on_data": UsageStatsEvents.DATA_CONTEXT_RUN_RULE_BASED_PROFILER_ON_DATA,
        "run_profiler_with_dynamic_arguments": UsageStatsEvents.DATA_CONTEXT_RUN_RULE_BASED_PROFILER_WITH_DYNAMIC_ARGUMENTS,
        "run_validation_operator": UsageStatsEvents.DATA_CONTEXT_RUN_VALIDATION_OPERATOR,
        "save_expectation_suite": UsageStatsEvents.DATA_CONTEXT_SAVE_EXPECTATION_SUITE,
    }


@mock.patch(
    "great_expectations.core.usage_statistics.usage_statistics.UsageStatisticsHandler.emit"
)
@pytest.mark.parametrize(
    "method_name,expected_event",
    [(name, event) for name, event in filter_enabled_methods(ENABLED_METHODS).items()],
)
@pytest.mark.parametrize(
    "data_context_fixture_name",
    [
        # In order to leverage existing fixtures in parametrization, we provide
        # their string names and dynamically retrieve them using pytest's built-in
        # `request` fixture.
        # Source: https://stackoverflow.com/a/64348247
        pytest.param("in_memory_runtime_context", id="EphemeralDataContext"),
        pytest.param("empty_data_context", id="FileDataContext"),
        pytest.param(
            "empty_data_context_in_cloud_mode",
            id="CloudDataContext",
        ),
    ],
)
@pytest.mark.integration
def test_all_relevant_context_methods_emit_usage_stats(
    mock_emit: mock.MagicMock,
    enable_usage_stats,  # Needs to be before context fixtures to ensure usage stats handlers are attached
    method_name: str,
    expected_event: UsageStatsEvents,
    data_context_fixture_name: str,
    request,
):
    """
    What does this test and why?

    Ensures that all primary context types (EphemeralDataContext, FileDataContext, and CloudDataContext)
    emit the same usage stats events.

    This guards against the case where a child class overrides a method defined by AbstractDataContext
    but forgets to add the decorator, resulting in us losing event data.
    """
    context = request.getfixturevalue(data_context_fixture_name)

    module_path = f"{context.__module__}.{context.__class__.__name__}.{method_name}"
    logger.info(f"Testing {module_path}")

    # Every usage stats decorated method should have a corresponding private method for actual business logic
    method_to_patch = module_path.replace(method_name, f"_{method_name}")

    with mock.patch(method_to_patch) as mock_fn:
        method = getattr(context, method_name)

        # Generate a set of dummy values to trigger the target method
        # and invoke the usage stats decorator without causing side-effects
        signature = inspect.signature(method)
        kwargs = {param: None for param in signature.parameters}
        method(**kwargs)

        mock_fn.assert_called_once()

    mock_calls = mock_emit.call_args_list
    assert len(mock_calls) == 2

    init_call, latest_call = mock_calls
    init_event = init_call[0][0]["event"]
    latest_event = latest_call[0][0]["event"]
    assert init_event == UsageStatsEvents.DATA_CONTEXT___INIT__
    assert latest_event == expected_event
