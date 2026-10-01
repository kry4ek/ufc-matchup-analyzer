"""Public comparison reports preserve model outputs and use explicit units."""
import copy
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from analyzer_results import format_result


def matchup():
    """Small fixture uses the same JSON names as the retained engines."""
    return {
        'fighter_a': 'José Alpha', 'fighter_b': 'Zoë Beta',
        'fight_date': '2025-01-18', 'division': 'Lightweight',
        'fighter_a_win_probability': .6, 'fighter_b_win_probability': .4,
        'predicted_winner': 'José Alpha', 'confidence_tier': 'medium',
        'model_version': 'v3_bayes_smoothed',
        'actual_max_training_event_date_used': '2025-01-11',
        'source_training_date_max': '2026-09-26',
        'training_rows': 14074, 'training_unique_fights': 7037,
        'training_filter_cutoff': 'event_date <= 2025-01-17',
        'as_of_date': '2025-01-17', 'elapsed_seconds': 12.3,
        'fighter_a_snapshot': {
            'age_at_fight': 30.25, 'height_cm': 180.34, 'reach_cm': 182.88,
            'stance': 'Southpaw', 'ufc_fights_before': 10,
            'ufc_wins_before': 8, 'ufc_losses_before': 2,
            'ufc_win_pct_before': .8, 'current_win_streak': 0,
            'current_loss_streak': 1,
            'career_sig_str_accuracy_before': .45,
            'career_sig_str_defense_before': .6,
            'career_slpm_before': 3.25, 'career_sapm_before': 2.1,
            'career_td_avg_per15_before': 0,
            'career_td_accuracy_before': 0,
            'career_td_defense_before': .75,
            'last_3_win_pct': 1 / 3,
            'history_max_event_date_before': '2024-12-01',
        },
        'fighter_b_snapshot': {
            'age_at_fight': 32.5, 'height_cm': 177.8, 'reach_cm': 185.42,
            'stance': 'Orthodox', 'ufc_fights_before': 6,
            'ufc_wins_before': 3, 'ufc_losses_before': 3,
            'ufc_win_pct_before': .5, 'current_win_streak': 2,
            'current_loss_streak': 0,
            'career_sig_str_accuracy_before': .6,
            'career_sig_str_defense_before': .55,
            'career_slpm_before': 4.5, 'career_sapm_before': 3.3,
            'career_td_avg_per15_before': 1.25,
            'career_td_accuracy_before': .5,
            'career_td_defense_before': .9,
            'last_3_win_pct': 2 / 3,
            'history_max_event_date_before': '2024-11-16',
        },
        'feature_summary': {
            'fighter_a_elo_before': 1620.25,
            'fighter_b_elo_before': 1540.5,
            'fighter_a_division_elo_before': 0,
            'fighter_b_division_elo_before': 1500,
        },
        'warnings': [],
    }


def row(text, label):
    """Read semantic cells without coupling tests to padded column widths."""
    matching = [line for line in text.splitlines()
                if '|' in line and line.split('|')[0].strip() == label]
    if len(matching) != 1:
        raise AssertionError(f'Expected one table row for {label!r}, got {matching!r}')
    return [part.strip() for part in matching[0].split('|')[1:]]


class DetailedReportTests(unittest.TestCase):
    def test_men_selected_bayes_variants_and_attempt_support(self):
        payload=matchup()
        for side,rate,support in [('a',.45,0),('b',.6,100)]:
            payload['fighter_'+side+'_comparison']={
                'v3_bayes_sig_str_acc_s20_women_style':rate,
                'v3_bayes_sig_str_acc_denominator_before':support,
                'v3_bayes_sig_str_acc_seb':.99,
            }
        text=format_result(payload)
        self.assertEqual(row(text,'Sig. strike accuracy (prior strength 20)'),['45.0%','60.0%','-15.0 pp'])
        self.assertEqual(row(text,'Sig. strike accuracy support (attempts)'),['0','100','-100'])
        self.assertNotIn('99.0%',text)
        self.assertNotIn('SEB',text)

    def test_women_allowed_accuracy_is_not_mislabeled_defense(self):
        payload=matchup();payload['model_version']='v1_current_ensemble'
        for side,rate,support in [('a',.4,250),('b',.5,300)]:
            payload['fighter_'+side+'_comparison']={
                'career_sig_str_allowed_accuracy_before_bayes_s20':rate,
                'career_sig_str_allowed_accuracy_before_bayes_s20_den_before':support,
            }
        text=format_result(payload)
        self.assertEqual(row(text,'Sig. strike opponent accuracy allowed (prior strength 20)'),['40.0%','50.0%','-10.0 pp'])
        self.assertIn('lower is better',text)

    def test_men_comparison_has_elo_and_actual_values(self):
        text = format_result(matchup())
        self.assertEqual(row(text, 'Overall Elo'), ['1620.25', '1540.50', '+79.75'])
        self.assertEqual(row(text, 'Division Elo'), ['0.00', '1500.00', '-1500.00'])
        self.assertEqual(row(text, 'UFC fights'), ['10', '6', '+4'])
        self.assertEqual(row(text, 'Sig. strike accuracy (%)'), ['45.0%', '60.0%', '-15.0 pp'])
        self.assertEqual(row(text, 'Takedown accuracy (%)'), ['0.0%', '50.0%', '-50.0 pp'])
        self.assertEqual(row(text, 'Last 3 win rate (%)'), ['33.3%', '66.7%', '-33.3 pp'])

    def test_zero_is_data_missing_is_not_zero(self):
        payload = matchup()
        payload['fighter_a_snapshot']['career_td_accuracy_before'] = None
        payload['fighter_b_snapshot']['career_td_accuracy_before'] = 0
        text = format_result(payload)
        self.assertEqual(row(text, 'Takedown accuracy (%)'), ['N/A', '0.0%', 'N/A'])
        self.assertIn('N/A', text)

    def test_nonfinite_values_are_not_displayed_as_numbers(self):
        payload = matchup()
        payload['fighter_a_snapshot']['career_sig_str_accuracy_before'] = float('nan')
        payload['fighter_b_snapshot']['career_sig_str_accuracy_before'] = float('inf')
        cells = row(format_result(payload), 'Sig. strike accuracy (%)')
        self.assertEqual(cells, ['N/A', 'N/A', 'N/A'])

    def test_forward_reverse_columns_and_differences_follow_fighters(self):
        original = matchup()
        reversed_payload = copy.deepcopy(original)
        for left, right in [('fighter_a', 'fighter_b'),
                            ('fighter_a_snapshot', 'fighter_b_snapshot'),
                            ('fighter_a_win_probability', 'fighter_b_win_probability')]:
            reversed_payload[left], reversed_payload[right] = original[right], original[left]
        summary = reversed_payload['feature_summary']
        for suffix in ('elo_before', 'division_elo_before'):
            summary['fighter_a_' + suffix], summary['fighter_b_' + suffix] = (
                original['feature_summary']['fighter_b_' + suffix],
                original['feature_summary']['fighter_a_' + suffix])
        text = format_result(reversed_payload)
        self.assertEqual(row(text, 'Overall Elo'), ['1540.50', '1620.25', '-79.75'])
        self.assertEqual(row(text, 'UFC fights'), ['6', '10', '-4'])
        self.assertEqual(row(text, 'Sig. strike accuracy (%)'), ['60.0%', '45.0%', '+15.0 pp'])
        self.assertIn('Zoë Beta vs José Alpha', text)
        self.assertIn('Predicted winner: José Alpha', text)

    def test_extra_comparison_data_exposes_opponent_strength(self):
        payload = matchup()
        payload['fighter_a_comparison'] = {'avg_opponent_elo_before': 1580.5}
        payload['fighter_b_comparison'] = {'avg_opponent_elo_before': 1490.25}
        self.assertEqual(row(format_result(payload), 'Avg opponent Elo'),
                         ['1580.50', '1490.25', '+90.25'])

    def test_known_absolute_elo_values_can_be_recovered_from_difference_rows(self):
        payload = matchup()
        payload.pop('feature_summary')
        payload['top_feature_differences'] = [
            {'feature': 'elo_diff', 'fighter_a_value': 1700,
             'fighter_b_value': 1550, 'difference': 150},
            # A difference alone cannot tell us either fighter's Elo.
            {'feature': 'division_elo_diff', 'fighter_a_value': None,
             'fighter_b_value': None, 'difference': 80},
        ]
        text = format_result(payload)
        self.assertEqual(row(text, 'Overall Elo'), ['1700.00', '1550.00', '+150.00'])
        self.assertEqual(row(text, 'Division Elo'), ['N/A', 'N/A', 'N/A'])

    def test_report_does_not_mutate_prediction_or_round_json_probabilities(self):
        payload = matchup()
        payload['fighter_a_win_probability'] = .600123456789
        payload['fighter_b_win_probability'] = 1 - payload['fighter_a_win_probability']
        before = copy.deepcopy(payload)
        text = format_result(payload)
        self.assertEqual(payload, before)
        self.assertIn('José Alpha: 60.0%', text)
        self.assertIn('Zoë Beta: 40.0%', text)

    def test_historical_cutoff_is_actual_not_latest_full_dataset_date(self):
        text = format_result(matchup())
        self.assertIn('Latest training fight used: 2025-01-11', text)
        self.assertNotIn('Latest training fight used: 2026-09-26', text)
        self.assertIn('2025-01-17', text)

    def test_internal_paths_and_method_source_details_are_not_exposed(self):
        payload = matchup()
        payload['training_data'] = r'E:\research\private\training.csv'
        payload['stats_data'] = r'Z:\internal\stats.csv'
        payload['fighter_a_snapshot']['_method_source_columns'] = 'internal_parser_column'
        text = format_result(payload)
        for private in ('E:\\research', 'Z:\\internal', 'internal_parser_column'):
            self.assertNotIn(private, text)

    def test_legacy_minimal_payload_still_formats_without_datasets(self):
        payload = matchup()
        for field in ('fighter_a_snapshot', 'fighter_b_snapshot', 'feature_summary'):
            payload.pop(field)
        text = format_result(payload)
        self.assertIn('José Alpha vs Zoë Beta', text)
        self.assertIn('60.0%', text)
        self.assertIn('N/A', text)
        self.assertTrue(text.endswith('\n'))

    def test_women_model_outputs_are_distinguished_from_selected_probability(self):
        payload = matchup()
        payload.pop('confidence_tier')
        payload['model_version'] = 'v1_current_ensemble'
        payload['division'] = "Women's Flyweight"
        payload.update(
            ensemble_probability=.55, ensemble_confidence=.55,
            gb_shallow_primary_fighter_a_win_probability=.6,
            gb_shallow_primary_fighter_b_win_probability=.4,
            gb_shallow_primary_direction_disagreement=.012,
            cal_rf_sigmoid_challenger_fighter_a_win_probability=.55,
            cal_rf_sigmoid_challenger_fighter_b_win_probability=.45,
            cal_rf_sigmoid_challenger_direction_disagreement=.001,
            logistic_c025_sanity_fighter_a_win_probability=.51,
            logistic_c025_sanity_fighter_b_win_probability=.49,
            logistic_c025_sanity_direction_disagreement=0,
            reliability_label='Medium', reliability_score=64,
            model_spread=.09, direction_disagreement=.004,
            model_vote='José Alpha 3-0',
            reliability_meaning='Reliability estimates stability of the model probability.',
            reliability_note='Sparse takedown history requires caution.',
            min_ufc_fights=6, strike_support_level='high',
            strike_support_min_denominator=250,
            td_support_level='low', td_support_min_denominator=3,
            missing_final_feature_count=0,
        )
        payload['fighter_a_snapshot'].update(pre_elo=1600.5, pre_division_elo=1510.25)
        payload['fighter_b_snapshot'].update(pre_elo=1530.25, pre_division_elo=1500)
        payload.pop('feature_summary')
        before = copy.deepcopy(payload)
        text = format_result(payload)
        self.assertIn('José Alpha: 60.0%', text)
        self.assertIn('Zoë Beta: 40.0%', text)
        ensemble_rows = [line for line in text.splitlines() if re.search('ensemble', line, re.I)]
        self.assertTrue(any('55.0%' in line for line in ensemble_rows), ensemble_rows)
        self.assertIn('51.0%', text)
        self.assertIn('49.0%', text)
        self.assertIn('64/100', text)
        self.assertIn('Sparse takedown history requires caution.', text)
        self.assertEqual(row(text, 'Overall Elo'), ['1600.50', '1530.25', '+70.25'])
        self.assertEqual(payload, before)


if __name__ == '__main__':
    unittest.main()
