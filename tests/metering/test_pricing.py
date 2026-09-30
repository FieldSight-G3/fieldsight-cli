"""Model prices are typed config: exact dollar math, cross-region profiles priced as the base model, env overrides."""

from decimal import Decimal

import pytest

from fieldsight.harness.metering.pricing import PricingConfig, UnpricedModel


def test_cost_is_input_and_output_tokens_at_their_own_rates():
    pricing = PricingConfig()

    assert pricing.cost("deepseek.v3.2", 1_000_000, 1_000_000) == Decimal("2.47")
    assert pricing.cost("deepseek.v3.2", 6000, 800) == Decimal("0.00520")
    assert pricing.cost("amazon.titan-embed-text-v2:0", 1_000_000, 0) == Decimal("0.02")


def test_a_cross_region_inference_profile_costs_the_same_as_its_model():
    pricing = PricingConfig()

    assert pricing.cost("us.deepseek.v3.2", 1000, 1000) == pricing.cost("deepseek.v3.2", 1000, 1000)


def test_an_unpriced_model_fails_instead_of_counting_as_free():
    with pytest.raises(UnpricedModel):
        PricingConfig().cost("anthropic.some-other-model", 10, 10)


def test_prices_can_be_overridden_per_environment():
    pricing = PricingConfig.from_environment(
        {"FIELDSIGHT_PRICING_JSON": '{"deepseek.v3.2": {"input_per_million": "1.00", "output_per_million": "2.00"}}'})

    assert pricing.cost("deepseek.v3.2", 1_000_000, 1_000_000) == Decimal("3.00")
    # models it doesn't name keep their defaults
    assert pricing.cost("amazon.titan-embed-text-v2:0", 1_000_000, 0) == Decimal("0.02")
