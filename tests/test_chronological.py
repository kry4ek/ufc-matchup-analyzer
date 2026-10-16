import sys
from pathlib import Path
import unittest
from unittest import mock
import numpy as np
import pandas as pd
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'womens_ufc_model'))
try:
    import chronological_ensemble as model
except ModuleNotFoundError:
    model=None

def fixture():
    records = []
    for date in range(40):
        for bout in range(6):
            for side in (0, 1):
                records.append(dict(fight_id=f'{date}-{bout}', event_date=pd.Timestamp('2020-01-01')+pd.Timedelta(days=date),
                                    fighter_a_won=side, x=100*date+bout+side))
    return pd.DataFrame(records)

def pipeline(estimator, numeric, categorical):
    return Pipeline([('preprocess', StandardScaler()), ('clf', estimator)])

@unittest.skipIf(model is None, 'Candidate policy has not been promoted')
class Boundaries(unittest.TestCase):
    def test_preprocessor_fits_train_only(self):
        frame=fixture(); train,cal=model.calibration_split(model.metadata(frame))
        fitted,audit=model.fit_calibrated(LogisticRegression(),frame,['x'],['x'],[],pipeline)
        scaler=fitted.calibrated_classifiers_[0].estimator.named_steps['preprocess']
        self.assertAlmostEqual(float(scaler.mean_[0]),frame.iloc[train].x.mean())
        self.assertNotAlmostEqual(float(scaler.mean_[0]),frame.x.mean())
        self.assertEqual(audit['overlapping_bouts'],0)
    def test_nested_indices_resolve_to_outer_train(self):
        frame=fixture().sample(frac=1,random_state=7)
        with mock.patch.object(model,'base_models',return_value={'logistic':LogisticRegression()}):
            fitted,weights,audit=model.fit_ensemble(frame,['x'],['x'],[],pipeline)
        source=frame.reset_index(drop=True)
        for boundary in audit['boundaries']:
            parent=boundary.get('parent_train_indices')
            local=source.iloc[parent].reset_index(drop=True) if parent is not None else source
            a=local.iloc[boundary['train_indices']]; b=local.iloc[boundary['test_indices']]
            self.assertFalse(set(a.fight_id)&set(b.fight_id))
            self.assertLess(a.event_date.max(),b.event_date.min())
            if parent is not None:
                outer=[x for x in audit['boundaries'] if x.get('fold')==boundary['outer_fold']][0]
                self.assertFalse(set(b.fight_id)&set(source.iloc[outer['test_indices']].fight_id))
        self.assertAlmostEqual(sum(weights.values()),1)
        self.assertTrue(np.isfinite(fitted['logistic'].predict_proba(frame[['x']])).all())
    def test_corrupt_mirrors_fail_closed(self):
        for column,value in [('fight_id',''),('event_date',None),('fighter_a_won',2)]:
            frame=fixture();frame.loc[0,column]=value
            with self.assertRaises(ValueError): model.metadata(frame)
        with self.assertRaises(ValueError):model.metadata(fixture().iloc[1:])
    def test_same_date_is_never_split(self):
        rows=model.metadata(fixture())
        for a,b in model.weighting_splits(rows):
            self.assertFalse(set(rows.iloc[a].event_date)&set(rows.iloc[b].event_date))
    def test_insufficient_history_never_uses_random_folds(self):
        with self.assertRaisesRegex(ValueError,'16 event'):model.weighting_splits(model.metadata(fixture().iloc[:80]))

if __name__=='__main__':unittest.main(verbosity=2)

