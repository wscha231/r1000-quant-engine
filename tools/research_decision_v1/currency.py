"""Explicit base-currency arithmetic; KRW remains the legacy default."""
from tools.research_decision_v1.data import number


def base_currency(context):
    value = context.get("base_currency", "KRW")
    if value not in {"USD", "KRW"}:
        raise ValueError("unsupported_base_currency")
    return value


def capital(context):
    currency = base_currency(context)
    if currency == "USD":
        if "capital_krw" in context:
            raise ValueError("ambiguous_capital_currency")
        return number(context["capital_base"], positive=True)
    value = number(context.get("capital_base", context.get("capital_krw")), positive=True)
    if "capital_base" in context and "capital_krw" in context and value != context["capital_krw"]:
        raise ValueError("conflicting_capital_amounts")
    return value


def local_to_base(context, currency, *, rate=None):
    if currency not in {"USD", "KRW"}:
        raise ValueError("unsupported_asset_currency")
    base = base_currency(context)
    if currency == base:
        return 1.
    spot = number(context["fx"]["spot"] if rate is None else rate, positive=True)
    return spot if currency == "USD" and base == "KRW" else 1. / spot


def scenario_fx_ratio(context, currency, name):
    if currency == base_currency(context):
        return 1.
    return local_to_base(context, currency, rate=context["fx"]["scenario_rates"][name]) / local_to_base(context, currency)


def with_capital(context, amount):
    result = dict(context, capital_base=amount)
    if base_currency(context) == "KRW":
        result["capital_krw"] = amount
    return result
