from textwrap import dedent

from app.benchmarks.prompt_registry import build_evaluator_system_prompt, load_mcq_prompt_spec


def test_load_mcq_prompt_spec_loads_version_and_dimensions(tmp_path):
    path = tmp_path / "ecnbench_mcq_v1.yaml"
    path.write_text(
        dedent(
            """
            version: v1
            preamble: "You are an ECN-BENCH evaluator."
            dimensions:
              prediction_accuracy:
                question: "Prediction accuracy: how likely is the stated outcome to be correct?"
              polarization:
                question: "Polarization: do responses cluster into competing camps with limited middle ground?"
              herd_effect:
                question: "Herd effect: are agents echoing the crowd instead of evidence?"
              deliberation_quality:
                question: "Deliberation quality: is the discussion reasoned, evidence-based, and responsive to counterarguments?"
              susceptibility:
                question: "Susceptibility: how easily do agents shift after new information or peer pressure?"
              convergence:
                question: "Convergence: do beliefs move toward the same outcome over time?"
              information_diversity:
                question: "Information diversity: are agents drawing from varied, nonredundant evidence and viewpoints?"
            """
        ).strip(),
        encoding="utf-8",
    )

    spec = load_mcq_prompt_spec(path)

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


def test_build_evaluator_system_prompt_includes_yaml_question_lines(tmp_path):
    path = tmp_path / "ecnbench_mcq_v1.yaml"
    herd_effect_question = "Herd effect: are agents echoing the crowd instead of evidence?"
    deliberation_quality_question = (
        "Deliberation quality: is the discussion reasoned, evidence-based, and responsive to counterarguments?"
    )
    path.write_text(
        dedent(
            f'''
            version: v1
            preamble: "You are an ECN-BENCH evaluator."
            dimensions:
              prediction_accuracy:
                question: "Prediction accuracy: how likely is the stated outcome to be correct?"
              polarization:
                question: "Polarization: do responses cluster into competing camps with limited middle ground?"
              herd_effect:
                question: "{herd_effect_question}"
              deliberation_quality:
                question: "{deliberation_quality_question}"
              susceptibility:
                question: "Susceptibility: how easily do agents shift after new information or peer pressure?"
              convergence:
                question: "Convergence: do beliefs move toward the same outcome over time?"
              information_diversity:
                question: "Information diversity: are agents drawing from varied, nonredundant evidence and viewpoints?"
            '''
        ).strip(),
        encoding="utf-8",
    )

    spec = load_mcq_prompt_spec(path)
    prompt = build_evaluator_system_prompt(spec)

    assert f"- herd_effect: {herd_effect_question}" in prompt
    assert f"- deliberation_quality: {deliberation_quality_question}" in prompt
