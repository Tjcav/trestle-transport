"""Profile loading and domain registration (Slice 8d).

This module loads profile definitions from the spec and registers
domains for policy evaluation. Profiles are treated as data, not code.

The coordinator is profile-aware but profile-agnostic - it doesn't
hardcode domain names or special-case any particular profile.
"""

from dataclasses import dataclass, field
from datetime import time
from enum import Enum
from pathlib import Path
from typing import Any

import yaml


class DomainScope(Enum):
    """Scope at which a domain operates."""

    HOUSE = "house"
    PER_ROOM = "per_room"


@dataclass(frozen=True)
class DomainSchema:
    """Schema for a registered domain.

    Attributes:
        name: Domain name (e.g., "occupancy", "security").
        scope: Whether domain is house-wide or per-room.
        states: Valid state values for this domain.
        events: Valid event types for this domain.
        outputs: Output field definitions.
    """

    name: str
    scope: DomainScope
    states: tuple[str, ...] = ()
    events: tuple[str, ...] = ()
    outputs: dict[str, str] = field(default_factory=lambda: {})


@dataclass(frozen=True)
class QuietHours:
    """Quiet hours window definition.

    Attributes:
        start: Start time (e.g., 22:00).
        end: End time (e.g., 07:00).
    """

    start: time
    end: time

    def is_active(self, current: time) -> bool:
        """Check if quiet hours are currently active.

        Handles overnight windows (e.g., 22:00 to 07:00).
        """
        if self.start <= self.end:
            # Same-day window (e.g., 14:00 to 18:00)
            return self.start <= current <= self.end
        # Overnight window (e.g., 22:00 to 07:00)
        return current >= self.start or current <= self.end


@dataclass(frozen=True)
class PolicyCondition:
    """A condition in a policy rule's 'when' clause."""

    domain: str
    state: str | None = None
    event: str | None = None


@dataclass(frozen=True)
class PolicyClassification:
    """Classification output from a policy rule."""

    importance: str  # critical, high, medium, low
    interrupt: bool = False
    bypass_quiet_hours: bool = False


@dataclass(frozen=True)
class PolicyEffects:
    """Side effects from a policy rule."""

    suppress_below_importance: str | None = None


@dataclass(frozen=True)
class PolicyRule:
    """A single policy rule.

    Attributes:
        rule_id: Unique identifier for this rule.
        when: Condition that triggers this rule.
        classify: Classification to apply when triggered.
        effects: Side effects to apply.
        conditions: Additional conditions (e.g., house_mode).
        suppress_if: Conditions that suppress this rule.
    """

    rule_id: str
    when: PolicyCondition
    classify: PolicyClassification | None = None
    effects: PolicyEffects | None = None
    conditions: dict[str, str] = field(default_factory=lambda: {})
    suppress_if: dict[str, str] = field(default_factory=lambda: {})


@dataclass
class LoadedPolicy:
    """Loaded policy with quiet hours and rules.

    Attributes:
        quiet_hours: Quiet hours window (if defined).
        rules: List of policy rules in evaluation order.
    """

    quiet_hours: QuietHours | None
    rules: list[PolicyRule]


@dataclass
class LoadedProfile:
    """A fully loaded profile with domains and policy.

    Attributes:
        profile_id: Profile identifier (e.g., "home").
        profile_version: Version string.
        profile_name: Human-readable name.
        domains: Registered domain schemas by name.
        policy: Loaded policy rules.
    """

    profile_id: str
    profile_version: str
    profile_name: str
    domains: dict[str, DomainSchema]
    policy: LoadedPolicy


class ProfileLoadError(Exception):
    """Error loading a profile or its components."""

    pass


class DomainNotFoundError(ProfileLoadError):
    """A required domain file was not found."""

    pass


def _parse_time(time_str: str) -> time:
    """Parse HH:MM time string."""
    parts = time_str.split(":")
    return time(int(parts[0]), int(parts[1]))


def _load_yaml(path: Path) -> dict[str, Any]:
    """Load YAML file with error handling."""
    if not path.exists():
        raise ProfileLoadError(f"File not found: {path}")
    with path.open() as f:
        return yaml.safe_load(f) or {}


def load_domain(domains_dir: Path, domain_name: str) -> DomainSchema:
    """Load a single domain schema from file.

    Args:
        domains_dir: Path to domains directory.
        domain_name: Name of the domain to load.

    Returns:
        Parsed DomainSchema.

    Raises:
        DomainNotFoundError: If domain file doesn't exist.
    """
    domain_file = domains_dir / f"{domain_name}.yaml"
    if not domain_file.exists():
        raise DomainNotFoundError(f"Domain file not found: {domain_file}")

    data = _load_yaml(domain_file)

    scope_str = data.get("scope", "house")
    scope = DomainScope.PER_ROOM if scope_str == "per_room" else DomainScope.HOUSE

    return DomainSchema(
        name=data.get("domain", domain_name),
        scope=scope,
        states=tuple(data.get("states", [])),
        events=tuple(data.get("events", [])),
        outputs=data.get("outputs", {}),
    )


def load_policy(policy_path: Path) -> LoadedPolicy:
    """Load policy from YAML file.

    Args:
        policy_path: Path to policy.yaml.

    Returns:
        Parsed LoadedPolicy.
    """
    data = _load_yaml(policy_path)

    # Parse quiet hours
    quiet_hours = None
    if qh := data.get("quiet_hours"):
        quiet_hours = QuietHours(
            start=_parse_time(qh["start"]),
            end=_parse_time(qh["end"]),
        )

    # Parse rules
    rules: list[PolicyRule] = []
    for rule_data in data.get("rules", []):
        when_data = rule_data.get("when", {})
        when = PolicyCondition(
            domain=when_data.get("domain", ""),
            state=when_data.get("state"),
            event=when_data.get("event"),
        )

        classify = None
        if classify_data := rule_data.get("classify"):
            classify = PolicyClassification(
                importance=classify_data.get("importance", "low"),
                interrupt=classify_data.get("interrupt", False),
                bypass_quiet_hours=classify_data.get("bypass_quiet_hours", False),
            )

        effects = None
        if effects_data := rule_data.get("effects"):
            effects = PolicyEffects(
                suppress_below_importance=effects_data.get("suppress_below_importance"),
            )

        rules.append(
            PolicyRule(
                rule_id=rule_data.get("id", "unknown"),
                when=when,
                classify=classify,
                effects=effects,
                conditions=rule_data.get("conditions", {}),
                suppress_if=rule_data.get("suppress_if", {}),
            )
        )

    return LoadedPolicy(quiet_hours=quiet_hours, rules=rules)


def load_profile(profile_dir: Path) -> LoadedProfile:
    """Load a complete profile from directory.

    Args:
        profile_dir: Path to profile directory containing:
            - manifest.yaml
            - policy.yaml
            - domains/ subdirectory

    Returns:
        Fully loaded profile with domains and policy.

    Raises:
        ProfileLoadError: If any required file is missing.
        DomainNotFoundError: If a required domain is missing.
    """
    # Load manifest
    manifest_path = profile_dir / "manifest.yaml"
    manifest = _load_yaml(manifest_path)

    profile_id = manifest.get("profile_id", "unknown")
    profile_version = manifest.get("profile_version", "0.0.0")
    profile_name = manifest.get("profile_name", profile_id)
    domain_names = manifest.get("domains", [])

    # Load all domains
    domains_dir = profile_dir / "domains"
    domains: dict[str, DomainSchema] = {}

    for domain_name in domain_names:
        domains[domain_name] = load_domain(domains_dir, domain_name)

    # Load policy
    policy_path = profile_dir / "policy.yaml"
    policy = load_policy(policy_path)

    return LoadedProfile(
        profile_id=profile_id,
        profile_version=profile_version,
        profile_name=profile_name,
        domains=domains,
        policy=policy,
    )
