"""US entry point; shared implementation also used by chronological replay."""
from tools.research_decision_v1.engine import run_decisions, replay_export
from tools.research_decision_v1.engine import validate_config as _validate

def validate_config(config):
    if config.get('market_profile')!='US_LISTED_USD_V1':raise ValueError('us_market_profile_required')
    _validate(config)
