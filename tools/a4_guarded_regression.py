"""One fixed extrapolation-resistant research challenger; no release or I/O.

The caller authenticates originals, rights, historical clocks and experiment
authority. Mathematical past-only folds do not grant any of those properties.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from tools import a4_daily_multifactor as daily

ARM = 'GUARDED_RIDGE22'
CLIP_Z = 3.0
NOVEL_Z = 5.0
MAX_ROWS = 10000
MAX_COLUMNS = 88


def need(condition, reason):
    if not condition:
        raise ValueError('A4_GUARDED_'+reason)


def specification():
    return dict(schema='a4-guarded-regression-v1', arm=ARM,
        standardization='TRAIN_MEAN_POPULATION_SD', constant_sd=1e-12,
        standardized_clip=CLIP_Z, mean_fallback_above_abs_z=NOVEL_Z,
        novel_constant_feature='MEAN_FALLBACK', penalty='N_TRAIN_TIMES_IDENTITY',
        output_support='TRAIN_TARGET_MIN_MAX', initial=756, fold_size=252,
        min_train=504, entry_delay=1, training_label_end='STRICTLY_BEFORE_TEST',
        extra_post_test_embargo=False, hyperparameter_search=False,
        production_or_source_admission=False, a3_a5_connected=False)


def predictions(x_train, y_train, x_test):
    """Train-only clipping, strong fixed shrinkage, novelty fallback and support.

    The fallback is part of the method declared before this comparison. It is
    not a retrospective edit to predictions from any previous experiment.
    """
    xt, y, xv = (np.asarray(v, dtype=float) for v in (x_train,y_train,x_test))
    need(xt.ndim==2 and xv.ndim==2 and y.ndim==1, 'DIMENSIONS')
    need(2<=len(xt)<=MAX_ROWS and 1<=len(xv)<=MAX_ROWS and
         len(y)==len(xt) and 1<=xt.shape[1]<=MAX_COLUMNS and
         xt.shape[1]==xv.shape[1], 'BOUNDS')
    need(all(np.isfinite(v).all() and (np.abs(v)<=1e100).all()
             for v in (xt,y,xv)), 'VALUES')
    mean, sd = xt.mean(axis=0), xt.std(axis=0)
    active = sd>1e-12
    baseline = float(y.mean())
    novel_constant = (np.abs(xv[:,~active]-mean[~active])>1e-12).any(axis=1)
    fallback = novel_constant.copy()
    beta = np.zeros(int(active.sum()))
    projected = np.zeros(len(xv),dtype=bool)
    forecast = np.full(len(xv),baseline)
    if active.any():
        train_z=(xt[:,active]-mean[active])/sd[active]
        test_z=(xv[:,active]-mean[active])/sd[active]
        fallback |= (np.abs(test_z)>NOVEL_Z).any(axis=1)
        train_z=np.clip(train_z,-CLIP_Z,CLIP_Z)
        test_z=np.clip(test_z,-CLIP_Z,CLIP_Z)
        beta=np.linalg.solve(train_z.T@train_z+len(xt)*np.eye(int(active.sum())),
                             train_z.T@(y-baseline))
        forecast=baseline+test_z@beta
        projected=(forecast<y.min())|(forecast>y.max())
        forecast=np.clip(forecast,y.min(),y.max())
        forecast[fallback]=baseline
    need(np.isfinite(forecast).all(), 'NONFINITE_RESULT')
    return forecast,dict(active_features=int(active.sum()),
        fallback_rows=int(fallback.sum()), novel_constant_rows=int(novel_constant.sum()),
        support_projection_rows=int((projected&~fallback).sum()),
        parameter_sha256=daily.digest(dict(specification=specification(),
            mean=mean.tolist(),sd=sd.tolist(),beta=beta.tolist(),
            baseline=baseline,support=[float(y.min()),float(y.max())])))


def walk_forward(panel, labels, *, horizon, complete):
    """Fixed expanding folds. Future labels never enter fitting/preprocessing.

    Predictions do not depend on test-label finiteness. Scoring separately
    selects mature outcomes, on the same cohort as the retained comparator.
    This is a pure helper, not a scheduler or permission to execute research.
    """
    need(isinstance(panel,pd.DataFrame) and panel.columns.is_unique, 'PANEL')
    daily.chronological_dates(panel.index)
    need(2<=len(panel)<=MAX_ROWS and 1<=len(panel.columns)<=MAX_COLUMNS, 'PANEL_BOUNDS')
    need(type(horizon) is int and horizon in daily.HORIZONS, 'HORIZON')
    if isinstance(labels,pd.Series):
        need(labels.index.equals(panel.index), 'LABEL_INDEX')
    if isinstance(complete,pd.Series):
        need(complete.index.equals(panel.index), 'COHORT_INDEX')
    x=panel.to_numpy(float);y=np.asarray(labels,dtype=float);mask=np.asarray(complete)
    need(y.shape==(len(panel),) and not np.isinf(y).any() and
         mask.shape==y.shape and mask.dtype==np.dtype(bool), 'LABELS_OR_COHORT')
    need(not np.isinf(x).any() and np.isfinite(x[mask]).all(), 'COHORT_VALUES')
    position=np.arange(len(panel));pred=np.full(len(panel),np.nan)
    base=pred.copy();folds=[]
    for first in range(756,len(panel),252):
        train=mask&np.isfinite(y)&(position+horizon+1<first)
        test=mask&(position>=first)&(position<first+252)
        if train.sum()<504 or not test.any():
            continue
        forecast,receipt=predictions(x[train],y[train],x[test])
        pred[test]=forecast;base[test]=float(y[train].mean())
        folds.append(dict(first_test_position=first,
            last_training_label_position=int(position[train][-1]+horizon+1),
            training_rows=int(train.sum()),test_rows=int(test.sum()),**receipt))
    return pred,base,folds
