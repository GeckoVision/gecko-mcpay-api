"""Pattern A drift test — config-parity across the THREE artifacts that must agree.

This is the "never-again" guard for the class of bug that left OKX news dark
(PR #150) and silently ran the ``EVENTS_SECRET`` HMAC on a dev fallback in prod:
a credential lands in one config artifact but not the others, so it never
reaches the container.

The three artifacts:
  1. ``infra/secrets-manifest.yml``  — the canonical SOURCE OF TRUTH (``boot_required``)
  2. ``infra/push-ssm-params.sh``    — what we PUSH to SSM (``PARAMS`` + ``REQUIRED_AT_BOOT``)
  3. ``infra/ecs-stack.yml``         — what the ECS task INJECTS (``secrets:`` ValueFrom)

Invariants (each is its own test so a single drift fails loudly, Pattern A style):

  A. ``boot_required`` (manifest) == ``REQUIRED_AT_BOOT`` (push script)
       The manifest's boot list is the canonical mirror of the push script's
       sentinel-placeholder map. Adding a boot param = touch both.

  B. ``boot_required`` ⊆ ECS ``secrets:``
       Every param that gets a sentinel pushed to SSM at boot MUST be injected
       into the task — otherwise the sentinel sits unused in SSM and runtime
       falls back to a hardcoded default. THIS IS THE EVENTS_SECRET /
       GECKO_RERANKER DRIFT: both are in REQUIRED_AT_BOOT but were missing from
       ecs-stack.yml. This test FAILS on those two until ecs-stack.yml is fixed.

  C. ECS ``secrets:`` ⊆ push-script ``PARAMS``
       Everything the task tries to inject must be a param the push script knows
       how to push — otherwise the ECS task hits ResourceInitializationError
       (param not found in SSM) on start.

Extending for a new boot-required provider cred:
  add it to (1) manifest ``boot_required``, (2) push script ``REQUIRED_AT_BOOT``
  (with a sentinel), and (3) ecs-stack.yml ``secrets:``. Miss any one and the
  matching test below fails with an explicit set-diff message.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

# Worktree-safe repo root: this file lives at <repo>/tests/.
_REPO_ROOT = Path(__file__).resolve().parents[1]
_MANIFEST = _REPO_ROOT / "infra" / "secrets-manifest.yml"
_PUSH_SCRIPT = _REPO_ROOT / "infra" / "push-ssm-params.sh"
_ECS_STACK = _REPO_ROOT / "infra" / "ecs-stack.yml"


class _CFNLoader(yaml.SafeLoader):
    """SafeLoader that tolerates CloudFormation ``!Ref``/``!If``/``!Sub`` tags."""


def _ignore_cfn_tag(loader: yaml.Loader, tag_suffix: str, node: yaml.Node) -> Any:
    if isinstance(node, yaml.ScalarNode):
        return loader.construct_scalar(node)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    return loader.construct_mapping(node)


_CFNLoader.add_multi_constructor("!", _ignore_cfn_tag)


def _manifest_boot_required() -> set[str]:
    data = yaml.safe_load(_MANIFEST.read_text())
    return set(data["boot_required"])


def _push_script_block(name: str) -> set[str]:
    """Extract the ``[KEY]=...`` names from a ``declare -A <name>=( ... )`` block."""
    txt = _PUSH_SCRIPT.read_text()
    m = re.search(rf"declare -A {re.escape(name)}=\((.*?)\n\)", txt, re.DOTALL)
    assert m is not None, f"{name} block not found in push-ssm-params.sh"
    return set(re.findall(r"\[(\w+)\]=", m.group(1)))


def _ecs_secret_names() -> set[str]:
    """Names under the container's ``Secrets:`` ValueFrom block in ecs-stack.yml.

    Parsed structurally via the CFN-tolerant YAML loader rather than regex so a
    secret commented-out or moved doesn't silently pass.
    """
    stack = yaml.load(_ECS_STACK.read_text(), Loader=_CFNLoader)
    container = stack["Resources"]["ApiTaskDef"]["Properties"]["ContainerDefinitions"][0]
    return {s["Name"] for s in container["Secrets"]}


# --- Invariant A — manifest boot_required == push-script REQUIRED_AT_BOOT -----


def test_manifest_boot_required_matches_push_script() -> None:
    manifest = _manifest_boot_required()
    push = _push_script_block("REQUIRED_AT_BOOT")
    missing_in_manifest = push - manifest
    extra_in_manifest = manifest - push
    assert not missing_in_manifest and not extra_in_manifest, (
        "secrets-manifest.yml `boot_required` drifted from push-ssm-params.sh "
        "REQUIRED_AT_BOOT.\n"
        f"  in push script but NOT in manifest: {sorted(missing_in_manifest)}\n"
        f"  in manifest but NOT in push script: {sorted(extra_in_manifest)}\n"
        "Both must list the same boot-sentinel params."
    )


# --- Invariant B — boot_required ⊆ ECS secrets (THE EVENTS_SECRET DRIFT) ------


def test_boot_required_params_are_injected_by_ecs() -> None:
    boot = _manifest_boot_required()
    ecs = _ecs_secret_names()
    never_injected = boot - ecs
    assert not never_injected, (
        "These params get a sentinel pushed to SSM at boot but are MISSING from "
        "ecs-stack.yml `secrets:` — so they're never injected into the task and "
        "runtime falls back to a hardcoded default (e.g. EVENTS_SECRET's HMAC dev "
        "secret runs in prod). Add a `secrets:` ValueFrom entry for each:\n"
        f"  {sorted(never_injected)}"
    )


# --- Invariant C — ECS secrets ⊆ push-script PARAMS --------------------------


def test_ecs_secrets_are_all_pushable() -> None:
    ecs = _ecs_secret_names()
    params = _push_script_block("PARAMS")
    not_pushable = ecs - params
    assert not not_pushable, (
        "ecs-stack.yml `secrets:` references SSM params that push-ssm-params.sh "
        "never pushes (PARAMS map) — the ECS task will hit "
        "ResourceInitializationError (parameter not found) on start. Add each to "
        "the PARAMS map:\n"
        f"  {sorted(not_pushable)}"
    )
