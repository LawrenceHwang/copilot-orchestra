"""
Model Router — resolves which model to use for each agent role.

Priority chain (highest to lowest):
  User Override  >  Orchestrator Choice  >  Config Preset  >  Hardcoded Default

Usage:
    router = ModelRouter(preset=ModelPreset.BALANCED, overrides={AgentRole.SECURITY: "claude-opus-4-6"})
    model = router.get_model(AgentRole.SECURITY)
"""

from enum import Enum
from typing import Any

from backend.logging_config import get_logger

logger = get_logger("model_router")

# Hardcoded fallback models (last resort in priority chain)
_HARDCODED_DEFAULTS: dict[str, str] = {
    "orchestrator": "claude-sonnet-4-6",
    "reviewer_1": "claude-sonnet-4-6",
    "reviewer_2": "claude-sonnet-4-6",
    "reviewer_3": "claude-sonnet-4-6",
    "synthesizer": "claude-sonnet-4-6",
}

_ECONOMY_MODEL = "claude-haiku-4-5-20251001"
_PERFORMANCE_MODEL = "claude-opus-4-6"


class AgentRole(str, Enum):
    ORCHESTRATOR = "orchestrator"
    REVIEWER_1 = "reviewer_1"
    REVIEWER_2 = "reviewer_2"
    REVIEWER_3 = "reviewer_3"
    SYNTHESIZER = "synthesizer"


class ModelPreset(str, Enum):
    BALANCED = "balanced"  # sensible defaults per role
    ECONOMY = "economy"  # cheapest model for all roles
    PERFORMANCE = "performance"  # best model for all roles
    FREE = "free"  # dynamically-discovered 0x models only
    AUTO = "auto"  # orchestrator picks at runtime


class ModelRouter:
    """
    Resolves the model to use for each agent role, applying the priority chain.

    Instances are created fresh per review from the request's preset and overrides.
    Orchestrator choices are set at runtime via set_orchestrator_choice().
    """

    def __init__(
        self,
        preset: ModelPreset = ModelPreset.BALANCED,
        overrides: dict[AgentRole, str] | None = None,
        default_models: dict[AgentRole, str] | None = None,
        available_models: list[Any] | None = None,
    ) -> None:
        self._preset = preset
        # User overrides (highest priority after hardcoded)
        self._user_overrides: dict[AgentRole, str] = overrides or {}
        # Orchestrator runtime choices (set during review)
        self._orchestrator_choices: dict[AgentRole, str] = {}
        # Custom defaults (used as base for balanced preset)
        self._custom_defaults: dict[AgentRole, str] = default_models or {}
        # Dynamically discovered free (0x) models from SDK metadata.
        self._free_model_ids: list[str] = self._discover_free_model_ids(available_models or [])
        self._selected_free_model: str | None = self._pick_preferred_free_model(
            self._free_model_ids
        )

        logger.debug(
            "ModelRouter created",
            preset=preset.value,
            user_overrides={k.value: v for k, v in self._user_overrides.items()},
            free_model_count=len(self._free_model_ids),
        )

    @staticmethod
    def _discover_free_model_ids(models: list[Any]) -> list[str]:
        """Return enabled model IDs whose billing multiplier is exactly 0.0."""
        free_ids: list[str] = []

        for model in models:
            model_id = getattr(model, "id", None)
            if not isinstance(model_id, str) or not model_id:
                continue

            policy = getattr(model, "policy", None)
            state = getattr(policy, "state", None)
            if state not in (None, "enabled"):
                continue

            billing = getattr(model, "billing", None)
            multiplier = getattr(billing, "multiplier", None)
            if multiplier is None:
                continue

            try:
                if float(multiplier) == 0.0:
                    free_ids.append(model_id)
            except (TypeError, ValueError):
                continue

        return sorted(set(free_ids))

    @staticmethod
    def _pick_preferred_free_model(free_ids: list[str]) -> str | None:
        """Pick a stable free model choice without hardcoding model IDs."""
        if not free_ids:
            return None
        # Stable deterministic choice keeps all roles on the same free model.
        return free_ids[0]

    def has_free_models(self) -> bool:
        """Whether dynamic discovery found at least one free (0x) model."""
        return bool(self._free_model_ids)

    def free_models(self) -> list[str]:
        """Return discovered free (0x) model IDs."""
        return list(self._free_model_ids)

    def get_model(self, role: AgentRole) -> str:
        """
        Return the model to use for the given role, applying the priority chain.

        Priority: user override > orchestrator choice > preset > default
        """
        # 1. User override (highest priority)
        if role in self._user_overrides:
            model = self._user_overrides[role]
            logger.debug("Model resolved via user override", role=role.value, model=model)
            return model

        # 2. Orchestrator choice (only set in auto mode)
        if role in self._orchestrator_choices:
            model = self._orchestrator_choices[role]
            logger.debug("Model resolved via orchestrator choice", role=role.value, model=model)
            return model

        # 3. Preset
        model = self._resolve_from_preset(role)
        logger.debug(
            "Model resolved via preset", role=role.value, preset=self._preset.value, model=model
        )
        return model

    def set_orchestrator_choice(self, role: AgentRole, model: str) -> None:
        """
        Record the orchestrator's model choice for a role (auto mode only).

        This is lower priority than user overrides — calling this when a user
        override exists has no effect on get_model() output.
        """
        self._orchestrator_choices[role] = model
        logger.info(
            "Orchestrator selected model",
            role=role.value,
            model=model,
            effective=role not in self._user_overrides,
        )

    def _resolve_from_preset(self, role: AgentRole) -> str:
        """Resolve model from the preset, falling back to custom defaults then hardcoded."""
        if self._preset == ModelPreset.ECONOMY:
            return _ECONOMY_MODEL

        if self._preset == ModelPreset.PERFORMANCE:
            return _PERFORMANCE_MODEL

        if self._preset == ModelPreset.FREE:
            if self._selected_free_model:
                return self._selected_free_model
            raise RuntimeError(
                "FREE preset selected but no free (0x) models were discovered "
                "from SDK model metadata"
            )

        # BALANCED or AUTO: use custom defaults, then hardcoded
        if role in self._custom_defaults:
            return self._custom_defaults[role]

        return _HARDCODED_DEFAULTS.get(role.value, "claude-sonnet-4-6")

    def summary(self) -> dict[str, str]:
        """Return the resolved model for every role (useful for logging/UI)."""
        return {role.value: self.get_model(role) for role in AgentRole}
