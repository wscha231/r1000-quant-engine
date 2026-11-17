"""Synthetic leakage, extrapolation and domain counterexamples only."""
from pathlib import Path
import sys
import unittest
import numpy as np
import pandas as pd
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools import a4_guarded_regression as guarded


class GuardedRegression(unittest.TestCase):
    def setUp(self):
        self.rng=np.random.default_rng(287)

    def test_unseen_scale_and_novel_constant_fall_back(self):
        x=np.column_stack([np.linspace(-1,1,600),np.zeros(600)])
        y=.01+.02*x[:,0]
        test=np.array([[178.,0.],[0.,1.],[.3,0.]])
        pred,pin=guarded.predictions(x,y,test)
        np.testing.assert_allclose(pred[:2],y.mean(),rtol=0,atol=1e-15)
        self.assertEqual(pin['fallback_rows'],2)
        self.assertEqual(pin['novel_constant_rows'],1)
        self.assertNotAlmostEqual(pred[2],y.mean())

    def test_valid_target_domains_remain_valid(self):
        x=self.rng.normal(size=(600,8));test=self.rng.normal(size=(40,8))
        for y in (self.rng.uniform(-.9,2,600),self.rng.uniform(-.9,0,600),
                  self.rng.uniform(0,2,600)):
            pred,_=guarded.predictions(x,y,test)
            self.assertTrue(((pred>=y.min())&(pred<=y.max())).all())

    def test_batch_has_no_test_distribution_preprocessing(self):
        x=self.rng.normal(size=(600,5));y=self.rng.normal(size=600)
        one,pin=guarded.predictions(x,y,x[:1])
        many,pin2=guarded.predictions(x,y,np.vstack([x[:1],np.full((20,5),178.)]))
        np.testing.assert_array_equal(one,many[:1])
        self.assertEqual(pin['parameter_sha256'],pin2['parameter_sha256'])

    def test_future_inputs_and_labels_do_not_change_first_fold(self):
        dates=pd.bdate_range('2000-01-03',periods=1600)
        x=pd.DataFrame(self.rng.normal(size=(1600,4)),index=dates)
        y=self.rng.normal(0,.02,1600);complete=np.ones(1600,dtype=bool)
        a,base,folds=guarded.walk_forward(x,y,horizon=63,complete=complete)
        later=x.copy();later.iloc[1008:]=1e6
        later_y=y.copy();later_y[756:]=-1e6
        b,base2,_=guarded.walk_forward(later,later_y,horizon=63,complete=complete)
        np.testing.assert_array_equal(a[756:1008],b[756:1008])
        np.testing.assert_array_equal(base[756:1008],base2[756:1008])
        for f in folds:
            self.assertLess(f['last_training_label_position'],f['first_test_position'])
        c,_,_=guarded.walk_forward(x.iloc[:1008],y[:1008],horizon=63,complete=complete[:1008])
        np.testing.assert_array_equal(a[:1008],c)

    def test_ineligible_and_unmatured_rows_do_not_enter_training(self):
        dates=pd.bdate_range('2000-01-03',periods=1100)
        x=pd.DataFrame(self.rng.normal(size=(1100,2)),index=dates)
        y=self.rng.normal(size=1100);complete=np.ones(1100,dtype=bool);complete[10]=False
        a,_,_=guarded.walk_forward(x,y,horizon=21,complete=complete)
        x.iloc[10]=1e90;y[10]=1e90;y[734:]=1e90
        b,_,_=guarded.walk_forward(x,y,horizon=21,complete=complete)
        np.testing.assert_array_equal(a[756:1008],b[756:1008])

    def test_constant_and_invalid_inputs(self):
        p,pin=guarded.predictions(np.zeros((600,2)),np.ones(600),np.zeros((3,2)))
        np.testing.assert_array_equal(p,np.ones(3));self.assertEqual(pin['active_features'],0)
        for bad in (np.nan,np.inf,1e200):
            with self.assertRaises(ValueError):
                guarded.predictions(np.array([[0.,bad],[1.,0.]]),np.ones(2),np.ones((1,2)))


if __name__=='__main__':unittest.main()
