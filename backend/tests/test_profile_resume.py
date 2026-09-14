import json

from app.services.entity_reader import EntityNode
from app.services.oasis_profile_generator import OasisAgentProfile, OasisProfileGenerator


def _valid_profile(index, name):
    return OasisAgentProfile(
        user_id=index,
        user_name=f"account_{index}",
        name=name,
        bio=f"Bio for {name}",
        persona=f"Persona for {name}",
        age=30,
        gender="other",
        mbti="ISTJ",
        country="US",
    )


def test_missing_required_llm_fields_retry_before_accepting(monkeypatch):
    generator = OasisProfileGenerator.__new__(OasisProfileGenerator)
    calls = []

    class FakeClient:
        def chat_json(self, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                return {"bio": "Official account", "persona": "Trade negotiator"}
            return {
                "bio": "Official account",
                "persona": "Trade negotiator",
                "age": 30,
                "gender": "other",
                "mbti": "ISTJ",
                "country": "US",
            }

    generator.llm_client = FakeClient()
    monkeypatch.setattr("time.sleep", lambda _: None)

    result = generator._generate_profile_with_llm(
        "Office of the United States Trade Representative",
        "TradeDepartment",
        "US trade agency",
        {},
        "Trade negotiations",
    )

    assert len(calls) == 2
    assert result["age"] == 30


def test_resume_only_invalid_profile_from_legacy_reddit_json(tmp_path, monkeypatch):
    entities = [
        EntityNode(uuid=f"uuid-{index}", name=name, labels=["TradeDepartment"], summary="", attributes={})
        for index, name in enumerate(["United States", "United Kingdom", "USTR"])
    ]
    reddit_path = tmp_path / "reddit_profiles.json"
    checkpoint_path = tmp_path / "profiles_checkpoint.json"
    old_profiles = [_valid_profile(0, "United States").to_reddit_format(),
                    _valid_profile(1, "United Kingdom").to_reddit_format(),
                    {"user_id": 2, "username": "ustr_old", "name": "USTR", "bio": "Agency", "persona": "Agency"}]
    reddit_path.write_text(json.dumps(old_profiles), encoding="utf-8")

    generator = OasisProfileGenerator.__new__(OasisProfileGenerator)
    generated = []

    def generate(entity, user_id, use_llm):
        generated.append(user_id)
        return _valid_profile(user_id, entity.name)

    monkeypatch.setattr(generator, "generate_profile_from_entity", generate)
    monkeypatch.setattr(generator, "_print_generated_profile", lambda *_: None)

    profiles = generator.generate_profiles_from_entities(
        entities,
        realtime_output_path=str(reddit_path),
        output_platform="reddit",
        checkpoint_path=str(checkpoint_path),
        parallel_count=1,
    )

    assert generated == [2]
    assert [profile.user_id for profile in profiles] == [0, 1, 2]
    assert len(json.loads(checkpoint_path.read_text(encoding="utf-8"))) == 3
    assert all("age" in item for item in json.loads(reddit_path.read_text(encoding="utf-8")))
