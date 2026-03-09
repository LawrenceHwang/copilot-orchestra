"""
Enterprise SDK compatibility patches for github-copilot-sdk.

Background
----------
Enterprise GitHub Copilot accounts are administered through a corporate
agreement.  The GitHub Copilot API may omit individual capability and billing
fields for these accounts — either because the feature is restricted by
enterprise policy, or because the information is managed at the organization
level and not exposed per-model.

The github-copilot-sdk (as of v0.1.32) treats several of those fields as
*required*, raising ``ValueError`` when they are absent.  This causes
``list_models()`` to fail for the *entire* model list, not just the model
missing a field.

Patches applied
---------------
Each patch is narrowly scoped: it fills in a safe, conservative default only
when a field is genuinely absent (``None``).  Fields that are present — even
as ``False`` or ``0`` — are never overridden.

  ModelSupports.vision
      ``bool`` flag.  Enterprise may omit it when vision is not permitted.
      Default: ``False`` (conservative — assume no vision support).

  ModelCapabilities.supports / ModelCapabilities.limits
      Nested objects.  Enterprise may strip the entire ``supports`` or
      ``limits`` block from the capabilities payload.
      Defaults: empty ``ModelSupports`` (all False) / empty ``ModelLimits``
      (all None).

  ModelPolicy.state / ModelPolicy.terms
      ``state`` identifies whether a model is enabled/disabled/unconfigured.
      ``terms`` is legal text that enterprise accounts manage through their
      master agreement and do not surface per-model.
      Defaults: ``"unconfigured"`` / ``""`` (empty string).

  ModelBilling.multiplier
      Cost multiplier used to detect free (0×) models.  Enterprise accounts
      typically have billing managed through a corporate agreement and do not
      expose per-model multipliers.
      Default: ``1.0`` (conservative — assume the model is not free, so it
      is never mistakenly selected by the FREE preset).

Removal
-------
These patches should be removed once the SDK handles optional capability
fields natively.  Each patch is guarded by ``_patched`` so calling
``apply_enterprise_sdk_patches()`` more than once is safe (idempotent).
"""

from typing import Any

import copilot.types as _sdk

_patched = False


def apply_enterprise_sdk_patches() -> None:
    """Apply all enterprise compatibility patches to the Copilot SDK.

    Call once before the SDK client is started.  Subsequent calls are no-ops.
    """
    global _patched
    if _patched:
        return
    _patch_model_supports()
    _patch_model_capabilities()
    _patch_model_policy()
    _patch_model_billing()
    _patched = True


# ---------------------------------------------------------------------------
# ModelSupports — vision capability flag
# ---------------------------------------------------------------------------

def _patch_model_supports() -> None:
    """Default ``vision`` to False when absent.

    Enterprise accounts that restrict image input do not return this field.
    """
    _original = _sdk.ModelSupports.from_dict

    def _from_dict(obj: Any) -> _sdk.ModelSupports:
        if isinstance(obj, dict) and obj.get("vision") is None:
            obj = {**obj, "vision": False}
        return _original(obj)

    _sdk.ModelSupports.from_dict = staticmethod(_from_dict)


# ---------------------------------------------------------------------------
# ModelCapabilities — supports / limits objects
# ---------------------------------------------------------------------------

def _patch_model_capabilities() -> None:
    """Default missing ``supports`` / ``limits`` to empty objects.

    Enterprise policy can strip the entire ``supports`` or ``limits`` block
    from a model's capability payload.
    """
    _original = _sdk.ModelCapabilities.from_dict

    def _from_dict(obj: Any) -> _sdk.ModelCapabilities:
        if isinstance(obj, dict):
            if obj.get("supports") is None:
                obj = {**obj, "supports": {}}
            if obj.get("limits") is None:
                obj = {**obj, "limits": {}}
        return _original(obj)

    _sdk.ModelCapabilities.from_dict = staticmethod(_from_dict)


# ---------------------------------------------------------------------------
# ModelPolicy — state / terms strings
# ---------------------------------------------------------------------------

def _patch_model_policy() -> None:
    """Default missing ``state`` to ``"unconfigured"`` and ``terms`` to ``""``.

    Enterprise accounts manage legal terms through a master agreement and do
    not surface per-model ``terms`` text.  ``state`` defaults to
    ``"unconfigured"`` so the model is not mistakenly treated as enabled or
    disabled based on a missing field.
    """
    _original = _sdk.ModelPolicy.from_dict

    def _from_dict(obj: Any) -> _sdk.ModelPolicy:
        if isinstance(obj, dict):
            if obj.get("state") is None:
                obj = {**obj, "state": "unconfigured"}
            if obj.get("terms") is None:
                obj = {**obj, "terms": ""}
        return _original(obj)

    _sdk.ModelPolicy.from_dict = staticmethod(_from_dict)


# ---------------------------------------------------------------------------
# ModelBilling — cost multiplier
# ---------------------------------------------------------------------------

def _patch_model_billing() -> None:
    """Default missing ``multiplier`` to ``1.0``.

    Enterprise accounts have billing managed at the organizational level and
    may not expose per-model cost multipliers.  Defaulting to ``1.0``
    (rather than ``0.0``) is intentionally conservative: it prevents an
    enterprise model with suppressed billing data from being selected by the
    FREE preset (which looks for models with a ``0.0`` multiplier).
    """
    _original = _sdk.ModelBilling.from_dict

    def _from_dict(obj: Any) -> _sdk.ModelBilling:
        if isinstance(obj, dict) and obj.get("multiplier") is None:
            obj = {**obj, "multiplier": 1.0}
        return _original(obj)

    _sdk.ModelBilling.from_dict = staticmethod(_from_dict)
