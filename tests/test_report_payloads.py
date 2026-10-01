"""Reporting must expose computed details without changing prediction results."""
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest import mock

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'mens_ufc_model'))
from src.prediction import prediction_engine as men
from src.features import mens_live_v3_bayes_features as v3
from src.features import mens_live_v2_features as v2

spec = importlib.util.spec_from_file_location(
    'women_report_payload_engine', ROOT / 'womens_ufc_model/predict_matchup_advanced.py')
women = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = women
spec.loader.exec_module(women)


class ReportPayloadTests(unittest.TestCase):
    def test_men_live_details_preserve_legacy_snapshots_and_probability(self):
        a = SimpleNamespace(fighter_name='Fighter A', fighter_id='a')
        b = SimpleNamespace(fighter_name='Fighter B', fighter_id='b')
        snap_a = {'age_at_fight': 29., 'ufc_fights_before': 8, 'stance': 'Orthodox'}
        snap_b = {'age_at_fight': 34., 'ufc_fights_before': 5, 'stance': 'Southpaw'}
        elo_a = {'elo_before': 1622., 'division_elo_before': 1500.,
                 'avg_opponent_elo_before': 1537., 'elo_recent_trend': 20.}
        elo_b = {'elo_before': 1546., 'division_elo_before': 1500.,
                 'avg_opponent_elo_before': 1503., 'elo_recent_trend': -5.}
        training = {key: None for key in (
            'as_of_date', 'as_of_date_source', 'training_filter_cutoff',
            'actual_max_training_event_date_used', 'source_training_date_max',
            'source_rows_after_as_of_date', 'source_unique_fights_after_as_of_date',
            'future_training_rows_allowed', 'training_rows', 'training_unique_fights',
            'training_date_min', 'training_date_max', 'excluded_rows_after_as_of_date',
            'excluded_unique_fights_after_as_of_date', 'excluded_rows_on_or_after_fight_date',
            'excluded_unique_fights_on_or_after_fight_date', 'features_used',
            'numeric_features', 'categorical_features')}
        training['actual_max_training_event_date_used'] = '2026-09-26'
        bundle = SimpleNamespace(features=[], model=None, model_name='logistic',
                                 model_version='v3_bayes_smoothed', feature_policy='unchanged',
                                 logistic_c=.1, training_summary=training)
        rows = SimpleNamespace(
            forward={'fighter_a_v3_bayes_sig_str_acc_denominator_before': 252.,
                     'fighter_b_v3_bayes_sig_str_acc_denominator_before': 300.,
                     'fighter_a_v3_bayes_sig_str_acc_s20_women_style': .453,
                     'fighter_b_v3_bayes_sig_str_acc_s20_women_style': .581},
            reverse={}, warnings=[],
            fighter_a_comparison={'avg_prior_opponent_elo_refined': 1510., 'finish_wins_before': 4},
            fighter_b_comparison={'avg_prior_opponent_elo_refined': 1550., 'finish_wins_before': 2})
        with mock.patch.object(v3, 'build_live_v3_bayes_feature_rows', return_value=rows), \
                mock.patch.object(men, 'predict_row', side_effect=[.8, .2]):
            payload = men.build_prediction_result(
                fighter_a=a, fighter_b=b, fight_date=pd.Timestamp('2026-10-04'),
                weight_class='Lightweight', snapshot_a=snap_a, snapshot_b=snap_b,
                elo_a=elo_a, elo_b=elo_b, model_bundle=bundle, live_v2_context=object())
        self.assertEqual(payload['fighter_a_snapshot'], snap_a)
        self.assertEqual(payload['fighter_b_snapshot'], snap_b)
        self.assertEqual(payload['fighter_a_comparison']['avg_opponent_elo_before'], 1537.)
        self.assertEqual(payload['fighter_b_comparison']['elo_recent_trend'], -5.)
        self.assertEqual(payload['fighter_a_comparison']['v3_bayes_sig_str_acc_denominator_before'], 252.)
        self.assertEqual(payload['fighter_b_comparison']['v3_bayes_sig_str_acc_s20_women_style'], .581)
        self.assertEqual(payload['fighter_a_comparison']['avg_prior_opponent_elo_refined'], 1510.)
        self.assertEqual(payload['fighter_b_comparison']['finish_wins_before'], 2)
        self.assertAlmostEqual(payload['fighter_a_final_probability'], .77)
        self.assertEqual(payload['actual_max_training_event_date_used'], '2026-09-26')
        json.dumps(men.serialize_prediction(payload), allow_nan=False)

    def test_men_report_snapshot_excludes_same_date_and_future_without_changing_pair_features(self):
        a = SimpleNamespace(fighter_name='Fighter A', fighter_id='a', details={})
        b = SimpleNamespace(fighter_name='Fighter B', fighter_id='b', details={})
        groups = []
        elo_lookup = {}
        for fight_id, day, winner, method in (
                ('prior', '2026-01-01', 'a', 'KO/TKO'),
                ('same_day', '2026-01-10', 'b', 'Submission'),
                ('future', '2026-01-11', 'b', 'Decision')):
            rows = []
            for fighter, opponent in ((a, b), (b, a)):
                won = fighter.fighter_id == winner
                rows.append({'fight_id': fight_id, 'event_date': pd.Timestamp(day),
                             'fighter_id': fighter.fighter_id, 'opponent_id': opponent.fighter_id,
                             'weight_class': 'Lightweight', 'result': 'win' if won else 'loss',
                             'won': int(won), 'method': method, 'round': 1,
                             'minutes': 2., 'scheduled_five_round': False})
                elo_lookup[(fight_id, fighter.fighter_id)] = 1510. if fighter is a else 1560.
            groups.append((pd.Timestamp(day), pd.DataFrame(rows)))
        context = v2.LiveV2Context(stats=pd.DataFrame(), fights=pd.DataFrame(),
                                  elo_lookup=elo_lookup, date_groups=groups)
        cutoff = pd.Timestamp('2026-01-10')
        result = v2.build_live_v2_feature_rows(context=context, fighter_a=a, fighter_b=b,
                                             fight_date=cutoff, weight_class='Lightweight')
        self.assertEqual(result.fighter_a_comparison['finish_wins_before'], 1)
        self.assertEqual(result.fighter_a_comparison['ko_tko_wins_before'], 1)
        self.assertEqual(result.fighter_a_comparison['submission_wins_before'], 0)
        self.assertEqual(result.fighter_b_comparison['decision_wins_before'], 0)
        self.assertEqual(result.fighter_b_comparison['finish_losses_before'], 1)
        self.assertEqual(result.fighter_a_comparison['avg_prior_opponent_elo_refined'], 1560.)
        self.assertEqual(result.fighter_a_comparison['v2_history_max_event_date_before'], pd.Timestamp('2026-01-01'))
        self.assertEqual(context.cursor_index, 1)
        original_a = v2._prediction_snapshot(
            fighter=a, fight_date=cutoff, weight_class='Lightweight', histories=context.histories,
            global_totals=context.global_totals, division_totals=context.division_totals)
        original_b = v2._prediction_snapshot(
            fighter=b, fight_date=cutoff, weight_class='Lightweight', histories=context.histories,
            global_totals=context.global_totals, division_totals=context.division_totals)
        self.assertNotIn('finish_wins_before', original_a)
        expected_forward = v2._pair_features(original_a, original_b)
        expected_reverse = v2._pair_features(original_b, original_a)
        self.assertEqual(men.serialize_prediction(result.forward), men.serialize_prediction(expected_forward))
        self.assertEqual(men.serialize_prediction(result.reverse), men.serialize_prediction(expected_reverse))
        self.assertNotIn('fighter_a_finish_wins_before', result.forward)

    def test_v3_forwards_report_copies_separately_from_model_columns(self):
        a = SimpleNamespace(fighter_name='A', fighter_id='a', details={})
        b = SimpleNamespace(fighter_name='B', fighter_id='b', details={})
        v2_rows = v2.LiveV2FeatureRows(
            forward={'rate_diff': .1}, reverse={'rate_diff': -.1}, warnings=[],
            fighter_a_comparison={'avg_prior_opponent_elo_refined': 1510.},
            fighter_b_comparison={'avg_prior_opponent_elo_refined': 1560.})
        context = SimpleNamespace(base_context=object(), v2_context=object(),
                                  strength_lookup={family.family: {} for family in v3.RATE_FAMILIES})
        snapshot = {'history_max_event_date_before': '2026-01-01', 'ufc_fights_before': 1}
        with mock.patch.object(v3, '_resolve_fighter', side_effect=[(a, []), (b, [])]), \
                mock.patch.object(v3, '_base_state_before', return_value={}), \
                mock.patch.object(v3, '_base_snapshot', return_value=snapshot), \
                mock.patch.object(v3, 'build_live_v2_feature_rows', return_value=v2_rows), \
                mock.patch.object(v3, 'strength_at', return_value=25.), \
                mock.patch.object(v3, '_candidate_pair_row', side_effect=[{'bayes_diff': .2}, {'bayes_diff': -.2}]):
            result = v3.build_live_v3_bayes_feature_rows(
                context=context, fighter_a='A', fighter_b='B', fight_date='2026-01-10',
                weight_class='Lightweight')
        self.assertEqual(result.forward, {'rate_diff': .1, 'bayes_diff': .2})
        self.assertEqual(result.reverse, {'rate_diff': -.1, 'bayes_diff': -.2})
        self.assertEqual(result.fighter_a_comparison, v2_rows.fighter_a_comparison)
        self.assertTrue(result.leakage_audit['same_date_excluded'])
        self.assertTrue(result.leakage_audit['target_fight_stats_excluded'])
        result.fighter_a_comparison['avg_prior_opponent_elo_refined'] = 999.
        self.assertEqual(v2_rows.fighter_a_comparison['avg_prior_opponent_elo_refined'], 1510.)

    def test_women_ensemble_and_full_reliability_are_preserved(self):
        snap_a = {'age_at_fight': 29., 'ufc_fights_before': 8, 'pre_elo': 1622.}
        snap_b = {'age_at_fight': 34., 'ufc_fights_before': 5, 'pre_elo': 1546.}
        predictions = pd.DataFrame([
            {'model': 'one', 'fighter_a_win_probability': .6,
             'fighter_b_win_probability': .4, 'direction_disagreement': np.float64(.01)},
            {'model': 'two', 'fighter_a_win_probability': .4,
             'fighter_b_win_probability': .6, 'direction_disagreement': np.float64(.02)}])
        ensemble = {'model': 'ensemble_average', 'fighter_a_win_probability': .55,
                    'fighter_b_win_probability': .45, 'direction_disagreement': .0125}
        weights = {'one': np.float64(.75), 'two': np.float64(.25)}
        reliability = {
            'label': 'Medium', 'score': 64,
            'notes': ['First note', 'Second note', 'Third note', 'Fourth note'],
            'factors': [{'factor': 'Bayesian strike support',
                         'status': 'high (min 252)', 'effect': 'positive'}]}
        row = pd.DataFrame([{
            'fighter_a_career_sig_str_accuracy_before_bayes_s20': .453,
            'fighter_b_career_sig_str_accuracy_before_bayes_s20': .581,
            'fighter_a_career_sig_str_accuracy_before_bayes_s20_den_before': np.float64(252.),
            'fighter_b_career_sig_str_accuracy_before_bayes_s20_den_before': np.float64(300.),
            'fighter_a_unknown_rate': np.nan}])
        payload = women.build_structured_prediction_summary(
            args=SimpleNamespace(division="Women's Flyweight"),
            fighter_a='Fighter A', fighter_b='Fighter B', fight_date=pd.Timestamp('2026-10-04'),
            train_path=Path('train.csv'), stats_path=Path('stats.csv'),
            model_train_df=pd.DataFrame([{}, {}]), train_df=pd.DataFrame([{}, {}, {}]),
            pred_df=predictions, ensemble_row=ensemble, reliability=reliability,
            primary_prob_a=.55, primary_confidence=.55, votes_for_a=1, votes_for_b=1,
            vote_text='split', model_spread=.2, model_input_status={},
            snapshot_a=snap_a, snapshot_b=snap_b, market_comparison=None, market_edge=None,
            ensemble_weights=weights, pred_row_forward=row)
        self.assertEqual(payload['fighter_a_snapshot'], snap_a)
        self.assertEqual(payload['fighter_b_snapshot'], snap_b)
        self.assertEqual(payload['fighter_a_comparison']['pre_elo'], 1622.)
        self.assertEqual(payload['fighter_a_comparison']['career_sig_str_accuracy_before_bayes_s20_den_before'], 252.)
        self.assertIsNone(payload['fighter_a_comparison']['unknown_rate'])
        self.assertEqual(payload['fighter_a_win_probability'], .55)
        self.assertEqual(payload['model_weights'], {'one': .75, 'two': .25})
        self.assertEqual(len(payload['model_predictions']), 3)
        self.assertEqual(payload['model_predictions'][-1], ensemble)
        self.assertEqual(payload['reliability_notes'], reliability['notes'])
        self.assertEqual(payload['reliability_factors'], reliability['factors'])
        json.dumps(payload, allow_nan=False)

    def test_nested_json_keeps_missing_distinct_from_zero(self):
        value = {'rows': [{'missing': np.nan, 'zero': np.int64(0),
                           'rate': np.float64(.5), 'absent': None}]}
        self.assertEqual(women.json_safe_value(value),
                         {'rows': [{'missing': None, 'zero': 0, 'rate': .5, 'absent': None}]})
        json.dumps(women.json_safe_value(value), allow_nan=False)


if __name__ == '__main__':
    unittest.main()
