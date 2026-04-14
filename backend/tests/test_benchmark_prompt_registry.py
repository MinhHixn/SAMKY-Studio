from pathlib import Path

from app.benchmarks.prompt_registry import build_evaluator_system_prompt, load_mcq_prompt_spec


REAL_PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "ecnbench_mcq_v1.yaml"


def test_load_mcq_prompt_spec_loads_version_and_dimensions():
    spec = load_mcq_prompt_spec(REAL_PROMPT_PATH)

    assert spec["version"] == "v1"
    assert set(spec["dimensions"]) == {
        "prediction_accuracy",
        "polarization",
        "herd_effect",
        "deliberation_quality",
        "susceptibility",
        "convergence",
        "information_diversity",
    }
    assert spec["dimensions"]["herd_effect"]["question"] == (
        "By round 4, what fraction of agents had adopted the plurality view?"
    )
    assert spec["dimensions"]["deliberation_quality"]["question"] == (
        "How much novel reasoning (not present in the seed document) appeared in agent exchanges?"
    )


def test_build_evaluator_system_prompt_includes_yaml_question_lines():
    spec = load_mcq_prompt_spec(REAL_PROMPT_PATH)
    prompt = build_evaluator_system_prompt(spec)

    assert "Dimension questions:" in prompt
    assert "- prediction_accuracy:" in prompt
    assert "- polarization:" in prompt
    assert (
        "- herd_effect: By round 4, what fraction of agents had adopted the plurality view?"
        in prompt
    )
    assert (
        "- deliberation_quality: How much novel reasoning (not present in the seed document) appeared in agent exchanges?"
        in prompt
    )
    assert "- susceptibility:" in prompt
    assert "- convergence:" in prompt
    assert "- information_diversity:" in prompt
