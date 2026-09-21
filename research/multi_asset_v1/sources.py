"""Bounded public research adapters using the existing safe HTTP/FRED reader."""
from __future__ import annotations

from datetime import datetime,timedelta,timezone
import hashlib
from urllib.parse import urlencode

from tools.macro_history_sources import exclusive,parse_graph,request_bytes
from .contracts import encoded,load_json,number,require,stamp


def candles(raw,asset,collected,sessions,clock,start,end):
    data=load_json(raw)
    require(isinstance(data,list) and 0<len(data)<=300,"coinbase_candle_count")
    require(asset["symbol"] in {"BTC-USD","ETH-USD"},"coinbase_product")
    require(clock in {"UTC_DAY","NYSE_CLOSE"},"coinbase_clock")
    step=86400 if clock=="UTC_DAY" else 3600
    closes={int(v.timestamp()):k for k,v in sessions.items()}
    seen=set();rows=[]
    for candle in data:
        require(isinstance(candle,list) and len(candle)==6,"coinbase_candle_schema")
        t=number(candle[0],0)
        require(t.is_integer() and int(t)%step==0 and t not in seen,"coinbase_time_grid")
        seen.add(t)
        low,high,opening,close,volume=[number(v,0) for v in candle[1:]]
        require(low>0 and low<=min(opening,close)<=max(opening,close)<=high,"coinbase_ohlc")
        if t<start or t+step>end:continue
        observed=datetime.fromtimestamp(t+step,timezone.utc)
        require(observed<=stamp(collected),"unfinished_crypto_bar")
        if clock=="NYSE_CLOSE" and int(t+step) not in closes:continue
        session=datetime.fromtimestamp(t,timezone.utc).date().isoformat() if clock=="UTC_DAY" else closes[int(t+step)]
        rows.append(dict(asset_id=asset["asset_id"],session=session,clock=clock,price=close,
            total_return_index=close,volume=volume if clock=="UTC_DAY" else None,
            source_bucket_volume=volume,source_bucket_seconds=step,
            return_basis="TOTAL_RETURN",return_method="UNSTAKED_SPOT_PRICE",unit="USD_PER_TOKEN",currency="USD",
            corporate_action_quarantine=False,observed_at=observed.isoformat(),available_at=collected,
            collected_at=collected,source="COINBASE_EXCHANGE",data_quality="OBSERVED",
            evidence_kind="FORWARD_CAPTURE",raw_sha256=hashlib.sha256(raw).hexdigest()))
    return sorted(rows,key=lambda r:r["session"])


def capture_crypto(asset,sessions,attempt,fetcher=request_bytes):
    rows=[];receipts=[]
    for clock,step,buckets in (("UTC_DAY",86400,280),("NYSE_CLOSE",3600,120)):
        now=datetime.now(timezone.utc)
        end=int(now.timestamp())//step*step
        start=end-step*buckets
        url="https://api.exchange.coinbase.com/products/"+asset["symbol"]+"/candles?"+urlencode(dict(granularity=step,start=datetime.fromtimestamp(start,timezone.utc).isoformat(),end=datetime.fromtimestamp(end,timezone.utc).isoformat()))
        try:
            raw=fetcher(url);collected=datetime.now(timezone.utc).isoformat()
            parsed=candles(raw,asset,collected,sessions,clock,start,end)
            raw_hash=hashlib.sha256(raw).hexdigest()
            exclusive(attempt/"raw"/raw_hash,raw)
            rows.extend(parsed)
            receipts.append(dict(asset_id=asset["asset_id"],clock=clock,status="CAPTURED_CURRENT_ONLY",rows=len(parsed),raw_sha256=raw_hash))
        except Exception:
            receipts.append(dict(asset_id=asset["asset_id"],clock=clock,status="BLOCKED",reason="provider_unavailable_or_schema"))
    if not any(r["clock"]=="UTC_DAY" for r in rows):
        # An explicit provider fallback retains the failed primary receipt.
        # It can supply UTC research observations only, never NY snapshots.
        try:
            url="https://query1.finance.yahoo.com/v8/finance/chart/"+asset["symbol"]+"?"+urlencode({"range":"2y","interval":"1d"})
            raw=fetcher(url);collected=datetime.now(timezone.utc).isoformat()
            parsed=crypto_chart(raw,asset,collected)
            raw_hash=hashlib.sha256(raw).hexdigest();exclusive(attempt/"raw"/raw_hash,raw)
            rows.extend(parsed)
            receipts.append(dict(asset_id=asset["asset_id"],clock="UTC_DAY",source="YAHOO_CHART",status="CAPTURED_CURRENT_PROXY",rows=len(parsed),raw_sha256=raw_hash))
        except Exception:
            receipts.append(dict(asset_id=asset["asset_id"],clock="UTC_DAY",source="YAHOO_CHART",status="BLOCKED",reason="fallback_provider_unavailable_or_schema"))
    return rows,receipts


def crypto_chart(raw,asset,collected):
    data=load_json(raw)
    require(not data["chart"].get("error"),"crypto_chart_error")
    result=data["chart"]["result"]
    require(isinstance(result,list) and len(result)==1,"crypto_chart_result")
    chart=result[0];meta=chart["meta"]
    require(meta.get("symbol")==asset["symbol"] and asset["symbol"] in {"BTC-USD","ETH-USD"},"crypto_chart_identity")
    require(meta.get("currency")=="USD" and meta.get("instrumentType")=="CRYPTOCURRENCY","crypto_chart_units")
    require(meta.get("exchangeTimezoneName") in {"UTC","Etc/UTC"},"crypto_chart_clock")
    quote=chart["indicators"]["quote"][0];times=chart["timestamp"]
    require(len(times)==len(quote["close"])==len(quote["volume"]),"crypto_chart_arrays")
    rows=[];seen=set()
    for i,t in enumerate(times):
        number(t,0)
        # Yahoo can include a current partial bar; exclude it using its end time.
        observed=datetime.fromtimestamp(t+86400,timezone.utc)
        if observed>stamp(collected):continue
        require(t%86400==0 and t not in seen,"crypto_chart_daily_grid")
        seen.add(t)
        if quote["close"][i] is None:continue
        price=number(quote["close"][i],0)
        require(price>0,"crypto_chart_price")
        rows.append(dict(asset_id=asset["asset_id"],session=datetime.fromtimestamp(t,timezone.utc).date().isoformat(),
            clock="UTC_DAY",price=price,total_return_index=price,
            volume=None if quote["volume"][i] is None else number(quote["volume"][i],0),
            return_basis="PROVIDER_ADJUSTED_CLOSE_PROXY",return_method="UNSTAKED_SPOT_PRICE_PROXY",unit="USD_PER_TOKEN",currency="USD",
            corporate_action_quarantine=False,observed_at=observed.isoformat(),available_at=collected,collected_at=collected,
            source="YAHOO_CHART",data_quality="OBSERVED",evidence_kind="FORWARD_CAPTURE",raw_sha256=hashlib.sha256(raw).hexdigest()))
    return sorted(rows,key=lambda r:r["session"])


def capture_spot_metrics(attempt,fetcher=request_bytes):
    rows=[];receipts=[]
    for series,subject,unit in (("DHHNGSP","NATURAL_GAS","USD_PER_MMBTU"),("DCOILWTICO","OIL","USD_PER_BARREL")):
        now=datetime.now(timezone.utc)
        start=(now-timedelta(days=45)).date().isoformat();through=now.date().isoformat()
        url="https://fred.stlouisfed.org/graph/fredgraph.csv?"+urlencode(dict(id=series,cosd=start,coed=through))
        try:
            raw=fetcher(url);collected=datetime.now(timezone.utc).isoformat()
            records,missing=parse_graph(raw,series,start,through,collected)
            latest=max(records,key=lambda r:r["observation_date"])
            raw_hash=hashlib.sha256(raw).hexdigest();exclusive(attempt/"raw"/raw_hash,raw)
            rows.append(dict(subject_id=subject,metric="spot",value=latest["value"],unit=unit,
                observation_date=latest["observation_date"],observed_at=latest["observation_date"]+"T00:00:00Z",
                observation_precision="DATE_LABEL_NOT_PUBLICATION_TIME",available_at=collected,collected_at=collected,
                source="FRED_CURRENT",data_quality="OBSERVED",evidence_kind="FORWARD_CAPTURE",raw_sha256=raw_hash))
            receipts.append(dict(subject_id=subject,series=series,status="CAPTURED_CURRENT_ONLY",missing_dates=missing,raw_sha256=raw_hash))
        except Exception:
            receipts.append(dict(subject_id=subject,series=series,status="BLOCKED",reason="provider_unavailable_or_schema"))
    return rows,receipts
