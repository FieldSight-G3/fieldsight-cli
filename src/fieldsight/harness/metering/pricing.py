""" typed model pricing: what a call costs, derived from its measured tokens (requirements §8, §13)

    One price source: the reasoning and fast tier prices in config (FIELDSIGHT_REASONING_PRICE_IN/_OUT and
    FIELDSIGHT_FAST_PRICE_IN/_OUT, USD per million tokens), keyed by the model ids config names. The turn meter and
    the run record (graph/trace.py) both price through PricingConfig, so they can't disagree.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from ...config import ModelPrice, settings
from ...errors import FieldSightError

MILLION = Decimal(1_000_000)
# cross-region inference profiles prefix the model id (us.amazon.nova-pro-v1:0); the price is the base model's
PROFILE_PREFIXES = ("us.", "eu.", "apac.", "global.")


class UnpricedModel(FieldSightError):
    """A model call has no configured price, so its cost can't count against the budget."""


def base_model(model_id: str) -> str:
    for prefix in PROFILE_PREFIXES:
        if model_id.startswith(prefix):
            return model_id[len(prefix):]
    return model_id


class PricingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    prices: dict[str, ModelPrice]

    @classmethod
    def from_settings(cls) -> PricingConfig:
        """ the reasoning and fast tier models, at the prices config holds for them """

        prices = {base_model(settings.bedrock_model_id): settings.reasoning_price,
                  base_model(settings.bedrock_fast_model_id): settings.fast_price}
        if settings.multimodal_price is not None:
            # the photo model, when it's its own (FIELDSIGHT_BEDROCK_MULTIMODAL_MODEL_ID); unpriced, the meter refuses it
            prices[base_model(settings.bedrock_multimodal_model_id)] = settings.multimodal_price
        return cls(prices=prices)

    def price(self, model_id: str) -> ModelPrice:
        base = base_model(model_id)
        if base not in self.prices:
            raise UnpricedModel(f"No price configured for {model_id}; only the reasoning and fast tier models are priced")
        return self.prices[base]

    def cost(self, model_id: str, input_tokens: int, output_tokens: int) -> Decimal:
        """ dollars for one call, from its token counts """

        price = self.price(model_id)
        return (Decimal(input_tokens) * price.input_per_mtok + Decimal(output_tokens) * price.output_per_mtok) / MILLION
