"""
Unit tests for ModelRouter — written BEFORE the implementation (TDD).

Tests cover: default model resolution, preset modes, user overrides,
orchestrator choices, and priority chain correctness.
"""

from types import SimpleNamespace

import pytest

from backend.orchestration.model_router import AgentRole, ModelPreset, ModelRouter


class TestModelRouterDefaults:
    def test_returns_default_orchestrator_model(self):
        router = ModelRouter()
        assert router.get_model(AgentRole.ORCHESTRATOR) == "claude-sonnet-4-6"

    def test_returns_default_reviewer_1_model(self):
        router = ModelRouter()
        assert router.get_model(AgentRole.REVIEWER_1) == "claude-sonnet-4-6"

    def test_returns_default_reviewer_2_model(self):
        router = ModelRouter()
        assert router.get_model(AgentRole.REVIEWER_2) == "claude-sonnet-4-6"

    def test_returns_default_reviewer_3_model(self):
        router = ModelRouter()
        assert router.get_model(AgentRole.REVIEWER_3) == "claude-sonnet-4-6"

    def test_balanced_preset_matches_defaults(self):
        router_default = ModelRouter()
        router_balanced = ModelRouter(preset=ModelPreset.BALANCED)
        for role in AgentRole:
            assert router_default.get_model(role) == router_balanced.get_model(role)


class TestModelRouterPresets:
    def test_economy_preset_uses_haiku_for_all_roles(self):
        router = ModelRouter(preset=ModelPreset.ECONOMY)
        for role in AgentRole:
            assert "haiku" in router.get_model(role).lower()

    def test_performance_preset_uses_opus_for_all_roles(self):
        router = ModelRouter(preset=ModelPreset.PERFORMANCE)
        for role in AgentRole:
            assert "opus" in router.get_model(role).lower()

    def test_auto_preset_falls_back_to_defaults_before_orchestrator_sets_choices(self):
        router = ModelRouter(preset=ModelPreset.AUTO)
        # Before orchestrator picks, should fall back to configured defaults
        model = router.get_model(AgentRole.REVIEWER_1)
        assert model  # not empty

    def test_free_preset_uses_discovered_zero_multiplier_model(self):
        models = [
            SimpleNamespace(
                id="paid-model",
                billing=SimpleNamespace(multiplier=1.0),
                policy=SimpleNamespace(state="enabled"),
            ),
            SimpleNamespace(
                id="free-model",
                billing=SimpleNamespace(multiplier=0.0),
                policy=SimpleNamespace(state="enabled"),
            ),
        ]
        router = ModelRouter(preset=ModelPreset.FREE, available_models=models)
        for role in AgentRole:
            assert router.get_model(role) == "free-model"

    def test_free_preset_raises_when_no_zero_multiplier_model(self):
        models = [
            SimpleNamespace(
                id="paid-model",
                billing=SimpleNamespace(multiplier=1.0),
                policy=SimpleNamespace(state="enabled"),
            )
        ]
        router = ModelRouter(preset=ModelPreset.FREE, available_models=models)
        with pytest.raises(RuntimeError, match=r"no free \(0x\) models"):
            router.get_model(AgentRole.REVIEWER_1)

    def test_free_discovery_ignores_disabled_models(self):
        models = [
            SimpleNamespace(
                id="disabled-free",
                billing=SimpleNamespace(multiplier=0.0),
                policy=SimpleNamespace(state="disabled"),
            ),
            SimpleNamespace(
                id="enabled-free",
                billing=SimpleNamespace(multiplier=0.0),
                policy=SimpleNamespace(state="enabled"),
            ),
        ]
        router = ModelRouter(preset=ModelPreset.FREE, available_models=models)
        assert router.has_free_models() is True
        assert router.free_models() == ["enabled-free"]


class TestModelRouterUserOverrides:
    def test_user_override_takes_precedence_over_preset(self):
        router = ModelRouter(
            preset=ModelPreset.ECONOMY,
            overrides={AgentRole.REVIEWER_1: "my-custom-model"},
        )
        assert router.get_model(AgentRole.REVIEWER_1) == "my-custom-model"

    def test_user_override_does_not_affect_other_roles(self):
        router = ModelRouter(
            preset=ModelPreset.ECONOMY,
            overrides={AgentRole.REVIEWER_1: "my-custom-model"},
        )
        # Reviewer 2 should still use economy preset (haiku)
        assert "haiku" in router.get_model(AgentRole.REVIEWER_2).lower()

    def test_multiple_user_overrides(self):
        overrides = {
            AgentRole.REVIEWER_1: "model-a",
            AgentRole.REVIEWER_2: "model-b",
        }
        router = ModelRouter(overrides=overrides)
        assert router.get_model(AgentRole.REVIEWER_1) == "model-a"
        assert router.get_model(AgentRole.REVIEWER_2) == "model-b"


class TestModelRouterOrchestratorChoices:
    def test_orchestrator_choice_overrides_preset(self):
        router = ModelRouter(preset=ModelPreset.ECONOMY)
        router.set_orchestrator_choice(AgentRole.REVIEWER_1, "orch-chosen-model")
        assert router.get_model(AgentRole.REVIEWER_1) == "orch-chosen-model"

    def test_user_override_beats_orchestrator_choice(self):
        router = ModelRouter(overrides={AgentRole.REVIEWER_1: "user-model"})
        router.set_orchestrator_choice(AgentRole.REVIEWER_1, "orch-model")
        assert router.get_model(AgentRole.REVIEWER_1) == "user-model"

    def test_orchestrator_choice_does_not_affect_other_roles(self):
        router = ModelRouter(preset=ModelPreset.ECONOMY)
        router.set_orchestrator_choice(AgentRole.REVIEWER_1, "special-model")
        assert "haiku" in router.get_model(AgentRole.REVIEWER_2).lower()

    def test_set_orchestrator_choice_is_idempotent(self):
        router = ModelRouter()
        router.set_orchestrator_choice(AgentRole.REVIEWER_1, "model-v1")
        router.set_orchestrator_choice(AgentRole.REVIEWER_1, "model-v2")
        assert router.get_model(AgentRole.REVIEWER_1) == "model-v2"


class TestModelRouterPriorityChain:
    def test_priority_user_over_orchestrator_over_preset(self):
        """Full priority chain: user > orchestrator > preset > default."""
        router = ModelRouter(
            preset=ModelPreset.ECONOMY,
            overrides={AgentRole.REVIEWER_1: "user-model"},
        )
        router.set_orchestrator_choice(AgentRole.REVIEWER_1, "orch-model")
        # User override wins
        assert router.get_model(AgentRole.REVIEWER_1) == "user-model"

    def test_orchestrator_over_preset_when_no_user_override(self):
        router = ModelRouter(preset=ModelPreset.ECONOMY)
        router.set_orchestrator_choice(AgentRole.REVIEWER_1, "orch-model")
        assert router.get_model(AgentRole.REVIEWER_1) == "orch-model"

    def test_preset_wins_when_no_overrides(self):
        router = ModelRouter(preset=ModelPreset.ECONOMY)
        assert "haiku" in router.get_model(AgentRole.REVIEWER_1).lower()


class TestModelRouterCustomDefaults:
    def test_custom_default_models_are_used(self):
        custom_defaults = {
            AgentRole.ORCHESTRATOR: "custom-orch",
            AgentRole.REVIEWER_1: "custom-rev1",
            AgentRole.REVIEWER_2: "custom-rev2",
            AgentRole.REVIEWER_3: "custom-rev3",
            AgentRole.SYNTHESIZER: "custom-synth",
        }
        router = ModelRouter(default_models=custom_defaults)
        for role, model in custom_defaults.items():
            assert router.get_model(role) == model

    def test_partial_custom_defaults_fall_back_to_hardcoded(self):
        custom_defaults = {AgentRole.REVIEWER_1: "custom-rev1"}
        router = ModelRouter(default_models=custom_defaults)
        assert router.get_model(AgentRole.REVIEWER_1) == "custom-rev1"
        # Other roles use hardcoded defaults
        assert router.get_model(AgentRole.REVIEWER_2)  # not empty
