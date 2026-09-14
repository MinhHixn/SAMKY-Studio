from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from flask import Flask

from app.services.report_agent import (
    ReportAgent, ReportManager, ReportOutline, ReportSection, ReportStatus,
)


def make_agent(outline_response=None):
    return ReportAgent(
        graph_id="graph_test", simulation_id="sim_test",
        simulation_requirement="Use the supplied cutoff and simulated evidence.",
        llm_client=SimpleNamespace(chat_json=Mock(return_value=outline_response)),
        graph_tools=SimpleNamespace(get_simulation_context=lambda **kwargs: {}),
    )


@pytest.mark.parametrize("response", [
    {}, {"sections": []}, [], None,
    {"title": "Report", "summary": "Summary", "sections": [{"title": "Only one"}]},
    {"title": "Report", "summary": "Summary", "sections": [{"title": ""}, {"title": "B"}]},
    {"title": "Report", "summary": "Summary", "sections": [None, {"title": "B"}]},
    {"title": "Report", "summary": "Summary", "sections": [{"title": "A"}] * 6},
])
def test_invalid_outline_uses_real_section_plan(response):
    outline = make_agent(response).plan_outline()
    assert 2 <= len(outline.sections) <= 5
    assert all(section.title.strip() for section in outline.sections)
    assert all(section.content == "" for section in outline.sections)


def test_valid_outline_is_preserved():
    response = {"title": "Tariff outlook", "summary": "Cutoff-limited analysis",
                "sections": [{"title": "Evidence"}, {"title": "Forecast"}]}
    outline = make_agent(response).plan_outline()
    assert outline.title == response["title"]
    assert [s.title for s in outline.sections] == ["Evidence", "Forecast"]


@pytest.mark.parametrize("content", [None, "", "  \n"])
def test_empty_section_is_failed_and_never_marked_completed(monkeypatch, tmp_path, content):
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(tmp_path))
    agent = make_agent()
    agent.plan_outline = lambda **kwargs: ReportOutline("Report", "Summary", [ReportSection("Evidence")])
    agent._generate_section_react = lambda **kwargs: content
    report = agent.generate_report(report_id="report_empty")
    assert report.status == ReportStatus.FAILED
    assert "no content" in report.error
    assert ReportManager.get_report("report_empty").status == ReportStatus.FAILED
    assert ReportManager.get_progress("report_empty")["status"] == "failed"


def test_zero_section_outline_cannot_complete(monkeypatch, tmp_path):
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(tmp_path))
    agent = make_agent()
    agent.plan_outline = lambda **kwargs: ReportOutline("Report", "", [])
    report = agent.generate_report(report_id="report_zero")
    assert report.status == ReportStatus.FAILED
    assert "without sections" in report.error


def test_generated_sections_are_available_without_agent_logs(monkeypatch, tmp_path):
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(tmp_path))
    agent = make_agent()
    agent.plan_outline = lambda **kwargs: ReportOutline("Report", "Summary", [ReportSection("Evidence")])
    agent._generate_section_react = lambda **kwargs: "Observed evidence from the simulation."
    report = agent.generate_report(report_id="report_valid")
    assert report.status == ReportStatus.COMPLETED
    loaded = ReportManager.get_report("report_valid")
    assert loaded.outline.sections[0].content == "Observed evidence from the simulation."
    assert "Observed evidence" in ReportManager.get_generated_sections("report_valid")[0]["content"]


def test_unexecuted_tool_call_cannot_be_published_as_a_finished_report(monkeypatch, tmp_path):
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(tmp_path))
    agent = make_agent()
    agent.plan_outline = lambda **kwargs: ReportOutline("Report", "Summary", [ReportSection("Evidence")])
    agent._generate_section_react = lambda **kwargs: 'I need more information.\n<｜DSML｜tool_call>{"name":"quick_search"}</｜DSML｜tool_call>'
    report = agent.generate_report(report_id="report_bad_tool")
    assert report.status == ReportStatus.FAILED
    assert "unexecuted tool call" in report.error


def test_chat_api_returns_text_and_tool_metadata(monkeypatch):
    from app.api import report as api
    state = SimpleNamespace(project_id="project_test", graph_id="graph_test")
    project = SimpleNamespace(graph_id="graph_test", simulation_requirement="Requirement")
    monkeypatch.setattr(api, "SimulationManager", lambda: SimpleNamespace(get_simulation=lambda _: state))
    monkeypatch.setattr(api.ProjectManager, "get_project", lambda _: project)
    monkeypatch.setattr(api, "GraphToolsService", lambda **kwargs: object())
    result = {"response": "A readable answer", "tool_calls": [{"name": "quick_search"}], "sources": ["source"]}
    monkeypatch.setattr(api, "ReportAgent", lambda **kwargs: SimpleNamespace(chat=lambda **kwargs: result))
    app = Flask(__name__)
    app.extensions["neo4j_storage"] = object()
    app.register_blueprint(api.report_bp, url_prefix="/api/report")
    response = app.test_client().post("/api/report/chat", json={"simulation_id": "sim_test", "message": "Question"})
    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data == {**result, "simulation_id": "sim_test"}
    assert isinstance(data["response"], str)
