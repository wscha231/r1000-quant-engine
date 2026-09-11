"""US-only continuous fund entry point, using the shared replay implementation."""
from tools.research_decision_v1.fund_replay import load_history, render
from tools.research_decision_v1.fund_replay import replay as _replay

def replay(manifest,events,config,packet_loader,**kwargs):
    if config.get('market_profile')!='US_LISTED_USD_V1':raise ValueError('fund_us_profile_required')
    return _replay(manifest,events,config,packet_loader,**kwargs)
