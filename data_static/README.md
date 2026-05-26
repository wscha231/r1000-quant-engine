Static data seeds used only as fallbacks.

`iwb_holdings_seed.csv` is a tracked Russell 1000 / IWB constituent seed. The
main pipeline uses it only when live IWB or broad base-universe sources fail and
no healthy cached candidate universe is available. It is not a signal source and
does not override historical membership data.
