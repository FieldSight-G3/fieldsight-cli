"""Model prices are typed config: exact dollar math, cross-region profiles priced as the base model, one price source."""

from decimal import Decimal

import pytest

from fieldsight.config import ModelPrice
from fieldsight.harness.metering import pricing
from fieldsight.harness.metering.pricing import PricingConfig, UnpricedModel

DEEPSEEK = PricingConfig(prices={"deepseek.v3.2": ModelPrice(input_per_mtok=Decimal("0.62"), output_per_mtok=Decimal("1.85"))})


def test_cost_is_input_and_output_tokens_at_their_own_rates():
    assert DEEPSEEK.cost("deepseek.v3.2", 1_000_000, 1_000_000) == Decimal("2.47")
    assert DEEPSEEK.cost("deepseek.v3.2", 6000, 800) == Decimal("0.00520")


def test_a_cross_region_inference_profile_costs_the_same_as_its_model():
    assert DEEPSEEK.cost("us.deepseek.v3.2", 1000, 1000) == DEEPSEEK.cost("deepseek.v3.2", 1000, 1000)


def test_an_unpriced_model_fails_instead_of_counting_as_free():
    with pytest.raises(UnpricedModel):
        DEEPSEEK.cost("anthropic.some-other-model", 10, 10)


def test_the_configured_tiers_are_priced_from_config(monkeypatch):
    monkeypatch.setattr(pricing.settings, "bedrock_model_id", "us.amazon.nova-pro-v1:0")
    monkeypatch.setattr(pricing.settings, "bedrock_fast_model_id", "us.amazon.nova-lite-v1:0")
    monkeypatch.setattr(pricing.settings, "reasoning_price", ModelPrice(input_per_mtok=Decimal("0.80"), output_per_mtok=Decimal("3.20")))
    monkeypatch.setattr(pricing.settings, "fast_price", ModelPrice(input_per_mtok=Decimal("0.06"), output_per_mtok=Decimal("0.24")))

    configured = PricingConfig.from_settings()

    assert configured.cost("us.amazon.nova-pro-v1:0", 1_000_000, 1_000_000) == Decimal("4.00")
    assert configured.cost("us.amazon.nova-lite-v1:0", 1_000_000, 1_000_000) == Decimal("0.30")
    with pytest.raises(UnpricedModel):
        configured.cost("deepseek.v3.2", 10, 10)
