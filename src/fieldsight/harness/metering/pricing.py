""" typed model pricing: what a call costs, derived from its measured tokens (requirements §8, §13)

    Defaults are Bedrock on-demand list prices in us-east-1, read from https://aws.amazon.com/bedrock/pricing/
    on 2026-09-29. Override per environment with FIELDSIGHT_PRICING_JSON, e.g.
    {"deepseek.v3.2": {"input_per_million": "0.62", "output_per_million": "1.85"}}
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from ...errors import FieldSightError

MILLION = Decimal(1_000_000)
# cross-region inference profiles prefix the model id (us.deepseek.v3.2); the price is the base model's
PROFILE_PREFIXES = ("us.", "eu.", "apac.", "global.")


class UnpricedModel(FieldSightError):
    """A model call has no configured price, so its cost can't count against the budget."""


class ModelPrice(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    input_per_million: Decimal = Field(ge=0)
    output_per_million: Decimal = Field(default=Decimal(0), ge=0)


DEFAULT_PRICES: dict[str, ModelPrice] = {
    "deepseek.v3.2": ModelPrice(input_per_million=Decimal("0.62"), output_per_million=Decimal("1.85")),
    "amazon.titan-embed-text-v2:0": ModelPrice(input_per_million=Decimal("0.02")),
}


class PricingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    prices: dict[str, ModelPrice] = Field(default_factory=lambda: dict(DEFAULT_PRICES))

    @classmethod
    def from_environment(cls, values: Mapping[str, str] | None = None) -> PricingConfig:
        """ the defaults, with any model FIELDSIGHT_PRICING_JSON names replaced """

        source = os.environ if values is None else values
        overrides = json.loads(source.get("FIELDSIGHT_PRICING_JSON") or "{}")
        return cls(prices={**DEFAULT_PRICES, **{model: ModelPrice.model_validate(price) for model, price in overrides.items()}})

    def price(self, model_id: str) -> ModelPrice:
        base = model_id
        for prefix in PROFILE_PREFIXES:
            if base.startswith(prefix):
                base = base[len(prefix):]
                break
        if base not in self.prices:
            raise UnpricedModel(f"No price configured for {model_id}; add it to FIELDSIGHT_PRICING_JSON")
        return self.prices[base]

    def cost(self, model_id: str, input_tokens: int, output_tokens: int) -> Decimal:
        """ dollars for one call, from its token counts """

        price = self.price(model_id)
        return (Decimal(input_tokens) * price.input_per_million + Decimal(output_tokens) * price.output_per_million) / MILLION
