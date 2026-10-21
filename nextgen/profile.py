"""
nextgen/profile.py
Unified Institutional User Profile & Configuration Subsystem.
Single source of truth for portfolio parameters, alpha model blend, execution guards, and automation.
"""

import os
import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional, Union

from core.data_engine import get_base_dir


class ProfileValidationError(ValueError):
    """Raised when user profile violates quantitative or operational invariants."""
    pass


@dataclass
class PortfolioConfig:
    capital: float = 1_000_000.0
    cash: float = 1_000_000.0
    top_n: int = 20
    exit_buffer_rank: int = 40
    universe: str = "NIFTY500"
    benchmark: str = "NIFTY500"
    sizing_model: str = "equal_weight"


@dataclass
class AlphaModelConfig:
    use_composite_alpha: bool = True
    weights: Dict[str, float] = field(
        default_factory=lambda: {
            "total_momentum": 0.45,
            "residual_momentum": 0.35,
            "delivery_flow": 0.20,
        }
    )


@dataclass
class ExecutionGuardsConfig:
    upper_circuit_veto: bool = True
    delivery_distribution_veto: bool = True
    deadband_inr: float = 2500.0
    deadband_pct: float = 1.5
    tax_aware_rebalance: bool = True
    max_sector_allocation: int = 2


@dataclass
class NotificationsConfig:
    telegram_enabled: bool = False
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""


@dataclass
class AutomationConfig:
    headless_schedule: str = "18:30"
    auto_fetch_latest: bool = True
    generate_kite_basket: bool = True


@dataclass
class UserProfile:
    schema_version: str = "1.0.0"
    user_name: str = "Default Investor"
    portfolio: PortfolioConfig = field(default_factory=PortfolioConfig)
    alpha_model: AlphaModelConfig = field(default_factory=AlphaModelConfig)
    execution_guards: ExecutionGuardsConfig = field(default_factory=ExecutionGuardsConfig)
    notifications: NotificationsConfig = field(default_factory=NotificationsConfig)
    automation: AutomationConfig = field(default_factory=AutomationConfig)

    def validate(self) -> Tuple[bool, List[str]]:
        """Interrogates all 5 quantitative validity constraints on configuration."""
        errors: List[str] = []

        # Portfolio constraints
        if self.portfolio.capital <= 0:
            errors.append(f"Capital must be strictly positive (got {self.portfolio.capital}).")
        if self.portfolio.cash < 0:
            errors.append(f"Cash cannot be negative (got {self.portfolio.cash}).")
        if not (1 <= self.portfolio.top_n <= 100):
            errors.append(f"top_n must be in range [1, 100] (got {self.portfolio.top_n}).")
        if self.portfolio.exit_buffer_rank < self.portfolio.top_n:
            errors.append(
                f"exit_buffer_rank ({self.portfolio.exit_buffer_rank}) cannot be less than top_n ({self.portfolio.top_n})."
            )

        # Alpha model weights
        if self.alpha_model.use_composite_alpha:
            total_weight = sum(self.alpha_model.weights.values())
            if abs(total_weight - 1.0) > 0.001:
                errors.append(
                    f"Composite alpha factor weights must sum to 1.0 ± 0.001 (sum={total_weight:.4f}, weights={self.alpha_model.weights})."
                )

        # Execution guards
        if self.execution_guards.deadband_inr < 0:
            errors.append(f"Deadband INR cannot be negative (got {self.execution_guards.deadband_inr}).")
        if self.execution_guards.deadband_pct < 0:
            errors.append(f"Deadband percentage cannot be negative (got {self.execution_guards.deadband_pct}).")
        if self.execution_guards.max_sector_allocation < 1:
            errors.append(f"max_sector_allocation must be >= 1 (got {self.execution_guards.max_sector_allocation}).")

        return (len(errors) == 0, errors)

    def to_dict(self) -> Dict[str, Any]:
        """Converts profile to clean serializable dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UserProfile":
        """Instantiates typed UserProfile from dictionary with graceful backward defaults."""
        p_data = data.get("portfolio", {})
        a_data = data.get("alpha_model", {})
        g_data = data.get("execution_guards", {})
        n_data = data.get("notifications", {})
        m_data = data.get("automation", {})

        return cls(
            schema_version=str(data.get("schema_version", "1.0.0")),
            user_name=str(data.get("user_name", "Default Investor")),
            portfolio=PortfolioConfig(
                capital=float(p_data.get("capital", 1_000_000.0)),
                cash=float(p_data.get("cash", 1_000_000.0)),
                top_n=int(p_data.get("top_n", 20)),
                exit_buffer_rank=int(p_data.get("exit_buffer_rank", 40)),
                universe=str(p_data.get("universe", "NIFTY500")),
                benchmark=str(p_data.get("benchmark", "NIFTY500")),
                sizing_model=str(p_data.get("sizing_model", "equal_weight")),
            ),
            alpha_model=AlphaModelConfig(
                use_composite_alpha=bool(a_data.get("use_composite_alpha", True)),
                weights=dict(a_data.get("weights", {"total_momentum": 0.45, "residual_momentum": 0.35, "delivery_flow": 0.20})),
            ),
            execution_guards=ExecutionGuardsConfig(
                upper_circuit_veto=bool(g_data.get("upper_circuit_veto", True)),
                delivery_distribution_veto=bool(g_data.get("delivery_distribution_veto", True)),
                deadband_inr=float(g_data.get("deadband_inr", 2500.0)),
                deadband_pct=float(g_data.get("deadband_pct", 1.5)),
                tax_aware_rebalance=bool(g_data.get("tax_aware_rebalance", True)),
                max_sector_allocation=int(g_data.get("max_sector_allocation", 2)),
            ),
            notifications=NotificationsConfig(
                telegram_enabled=bool(n_data.get("telegram_enabled", False)),
                telegram_bot_token=str(n_data.get("telegram_bot_token", "")),
                telegram_chat_id=str(n_data.get("telegram_chat_id", "")),
            ),
            automation=AutomationConfig(
                headless_schedule=str(m_data.get("headless_schedule", "18:30")),
                auto_fetch_latest=bool(m_data.get("auto_fetch_latest", True)),
                generate_kite_basket=bool(m_data.get("generate_kite_basket", True)),
            ),
        )


def get_default_profile() -> UserProfile:
    """Returns canonical institutional default profile."""
    return UserProfile()


def get_default_profile_path() -> Path:
    """Returns standard config/user_profile.json path."""
    return get_base_dir() / "config" / "user_profile.json"


def load_user_profile(path: Optional[Union[str, Path]] = None) -> UserProfile:
    """
    Loads UserProfile from target JSON path.
    Falls back to canonical default if file does not exist.
    """
    target = Path(path) if path is not None else get_default_profile_path()
    if not target.exists():
        return get_default_profile()

    try:
        with open(target, "r", encoding="utf-8") as f:
            data = json.load(f)
        profile = UserProfile.from_dict(data)
        is_valid, errors = profile.validate()
        if not is_valid:
            # Fall back to default if file is corrupted
            return get_default_profile()
        return profile
    except Exception:
        return get_default_profile()


def save_user_profile(profile: UserProfile, path: Optional[Union[str, Path]] = None) -> None:
    """
    Saves UserProfile to JSON file with atomic write.
    Raises ProfileValidationError if profile violates quantitative invariants.
    """
    is_valid, errors = profile.validate()
    if not is_valid:
        raise ProfileValidationError(f"Cannot save invalid profile: {errors}")

    target = Path(path) if path is not None else get_default_profile_path()
    target.parent.mkdir(parents=True, exist_ok=True)

    tmp_path = target.with_suffix(f".tmp.{os.getpid()}")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(profile.to_dict(), f, indent=2)
    os.replace(tmp_path, target)
