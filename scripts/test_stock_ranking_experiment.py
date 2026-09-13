import copy,unittest
import numpy as np
import run_stock_ranking_experiment as e

class RankingProtocol(unittest.TestCase):
    def test_future_targets_cannot_change_fitted_predictions(self):
        rng=np.random.default_rng(2);X=rng.normal(size=(400,4));Y=rng.normal(size=(400,2))
        X[::5,1]=np.nan
        meta=[dict(origin=f'{2000+i//40}-01-01',targetDate=f'{2000+i//40}-12-01') for i in range(400)]
        test=rng.normal(size=(12,4));profile=dict(max_iter=5,max_leaf_nodes=3,min_samples_leaf=10,l2_regularization=20.,learning_rate=.035)
        a,s=e.fit_predict(X,Y,meta,test,'2007-01-01',profile)
        changed=Y.copy();changed[280:]=1e8
        b,t=e.fit_predict(X,changed,meta,test,'2007-01-01',profile)
        self.assertEqual(s,t)
        for name in e.NAMES:np.testing.assert_array_equal(a[name],b[name])
        c,u=e.fit_predict(X[:280],Y[:280],meta[:280],test,'2007-01-01',profile)
        self.assertEqual(s,u)
        for name in e.NAMES:np.testing.assert_array_equal(a[name],c[name])

    def test_imputation_and_scaling_do_not_learn_test_distribution(self):
        train=np.array([[1.,np.nan],[2.,np.nan],[3.,np.nan]])
        test=np.array([[4.,99.],[np.nan,10.]])
        a,b=e.ridge_design(train,test,np.ones(3))
        c,d=e.ridge_design(train,np.array([[9999.,9999.]]),np.ones(3))
        np.testing.assert_equal(a,c)
        self.assertEqual(b.shape,(2,4))
        self.assertTrue(np.all(np.isfinite(b)))

    def test_no_candidate_selected_if_momentum_is_better(self):
        earlier={k:{'dateMeanIc':.1} for k in e.NAMES}
        earlier['momentum']={'dateMeanIc':.2}
        self.assertIsNone(e.select(earlier))
        earlier['ridgeRelative']['dateMeanIc']=.3
        self.assertEqual(e.select(earlier),'ridgeRelative')

    def test_future_market_label_subtraction_preserves_actual_ranking(self):
        values=[.1,-.2,.5,.9]
        self.assertAlmostEqual(e.safe_ic(values,np.array(values)-.8),1.)

if __name__=='__main__':unittest.main()
