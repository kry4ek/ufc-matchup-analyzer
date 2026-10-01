"""Shared fighter catalogue and input rules, with explicit identity selection."""
from __future__ import annotations
import argparse
import csv
import datetime as dt
import difflib
from pathlib import Path
import re
import unicodedata
import bisect
from analyzer_support import ROOT

MEN_DIVISIONS = ('Flyweight', 'Bantamweight', 'Featherweight', 'Lightweight', 'Welterweight', 'Middleweight', 'Light Heavyweight', 'Heavyweight', 'Catch Weight', 'Open Weight')
WOMEN_DIVISIONS = ('Strawweight', 'Flyweight', 'Bantamweight', 'Featherweight')

def key(name):
    return ' '.join(''.join(c for c in unicodedata.normalize('NFKD', name.casefold()) if not unicodedata.combining(c)).split())

def iso_date(value):
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise argparse.ArgumentTypeError('Use YYYY-MM-DD, for example 2026-10-10.')
    try:
        dt.date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError('Enter a real calendar date in YYYY-MM-DD format.') from exc
    return value

class IdentityError(ValueError):
    def __init__(self, message, candidates=(), ambiguous=False):
        super().__init__(message)
        self.candidates = list(candidates)
        self.ambiguous = ambiguous

class FighterCatalog:
    def to_payload(self):
        return dict(sex=self.sex,known={k:sorted(v) for k,v in self.known.items()},
                    details=[(list(identity),{k:v for k,v in row.items() if k in ('date_of_birth','dob','weight','weight_class','division')}) for identity,row in self.details.items()],
                    history=self.history)

    @classmethod
    def from_payload(cls, payload):
        self=object.__new__(cls);self.sex=payload['sex']
        self.known={k:{tuple(v) for v in values} for k,values in payload['known'].items()}
        self.details={tuple(identity):row for identity,row in payload['details']}
        self.history={k:[tuple(v) for v in values] for k,values in payload['history'].items()}
        self.history_dates={k:[v[0] for v in values] for k,values in self.history.items()}
        self.names=sorted({n for values in self.known.values() for n,_ in values},key=key)
        return self

    def __init__(self, sex, root=ROOT, profiles=None):
        if sex not in ('men', 'women'):
            raise ValueError('Choose men or women.')
        self.sex = sex
        root = Path(root)
        base = root / ('mens_ufc_model' if sex == 'men' else 'womens_ufc_model')
        path = base / ('data/raw/ufcstats_men/fighters.csv' if sex == 'men' else 'output_td_repaired/ufc_womens_fighter_fight_stats_td_control_repaired.csv')
        self.known = {}
        self.details = {}
        with path.open(encoding='utf-8-sig', newline='') as stream:
            for row in csv.DictReader(stream):
                name = row.get('fighter_name', row.get('fighter', '')).strip()
                identifier = row.get('fighter_id') or row.get('profile_url', '').rstrip('/').rsplit('/', 1)[-1]
                if not name:
                    continue
                self.known.setdefault(key(name), set()).add((name, identifier))
                previous = self.details.get((name, identifier), {})
                if (row.get('event_date') or '') >= (previous.get('event_date') or ''):
                    self.details[name, identifier] = row
        if profiles:
            with Path(profiles).open(encoding='utf-8-sig', newline='') as stream:
                for row in csv.DictReader(stream):
                    name = row.get('fighter', row.get('fighter_name', row.get('name', ''))).strip()
                    if name and key(name) not in self.known:
                        self.known[key(name)] = {(name, row.get('fighter_id', ''))}
                        self.details[name, row.get('fighter_id', '')] = row
        self.names = sorted({name for values in self.known.values() for name, _ in values}, key=key)
        self.history = {}
        self.history_dates = {}
        if sex == 'men':
            history_path = base / 'data/raw/ufcstats_men/fights.csv'
        else:
            history_path = path
        if history_path.exists():
            with history_path.open(encoding='utf-8-sig', newline='') as stream:
                for row in csv.DictReader(stream):
                    date = row.get('event_date', '')
                    if not date: continue
                    identities = (row.get('fighter_red_id'), row.get('fighter_blue_id')) if sex == 'men' else (row.get('fighter_id') or row.get('profile_url', '').rstrip('/').rsplit('/', 1)[-1],)
                    for identifier in identities:
                        if identifier:
                            self.history.setdefault(identifier, {})[row.get('fight_id') or date] = (date, row.get('weight_class') or row.get('division') or '')
            for identifier, values in self.history.items():
                self.history[identifier] = sorted(values.values())
                self.history_dates[identifier] = [v[0] for v in self.history[identifier]]

    def coverage(self, identity, fight_date, division):
        identifier = identity[1]
        records = self.history.get(identifier, [])
        records = records[:bisect.bisect_left(self.history_dates.get(identifier, []), fight_date)]
        normalized = key(division.replace("Women's ", ''))
        in_division = sum(key(d.replace("Women's ", '')) == normalized for _, d in records)
        return dict(fights=len(records), latest=records[-1][0] if records else None,
                    last_division=records[-1][1] if records else None, division_fights=in_division)

    def suggestion_description(self, identity, fight_date, division):
        info = self.coverage(identity, fight_date, division)
        details = f"{info['fights']} eligible UFC fights"
        if info['latest']: details += f"; last: {info['latest']}; {info['last_division']}"
        profile=self.details.get(identity,{})
        birth=profile.get('date_of_birth') or profile.get('dob')
        if birth:details+='; born: '+birth
        matches = self.known.get(key(identity[0]), ())
        if len(matches) > 1: details += '; ID: ' + identity[1]
        return identity[0] + ' — ' + details

    def suggestions(self, text, limit=12):
        needle = key(text)
        if len(needle) < 2: return []
        matches = [name for name in self.names if needle in key(name)]
        if matches:
            matches.sort(key=lambda n: (key(n) != needle, not key(n).startswith(needle), key(n)))
        else:
            close = difflib.get_close_matches(needle, sorted(self.known), n=3, cutoff=.60)
            matches = list(dict.fromkeys(n for k in close for n, _ in sorted(self.known[k])))
        return [identity for name in matches[:limit] for identity in sorted(self.known[key(name)])][:limit]

    def describe(self, identity):
        name, identifier = identity
        row = self.details.get(identity, {})
        details = []
        for label, value in [('born', row.get('date_of_birth') or row.get('dob')), ('weight', row.get('weight') or row.get('weight_class') or row.get('division')), ('last recorded fight', row.get('event_date'))]:
            if value:
                details.append(f'{label}: {value}')
        if identifier:
            details.append('ID: ' + identifier)
        return name + (' — ' + '; '.join(details) if details else '')

    def search(self, text, limit=12):
        needle = key(text)
        if not needle:
            return []
        return sorted((n for n in self.names if needle in key(n)), key=lambda n: (not key(n).startswith(needle), key(n)))[:limit]

    def resolve(self, name, fighter_id=None):
        if not name.strip():
            raise IdentityError('Enter both fighter names.')
        matches = self.known.get(key(name), set())
        if self.sex == 'women' and len(matches) > 1:
            raise IdentityError('Ambiguous fighter name: this women’s name belongs to multiple identities. The current model cannot distinguish them safely; choose another matchup or repair the dataset.')
        if fighter_id:
            matches = {x for x in matches if x[1] == fighter_id}
        if not matches:
            nearest = difflib.get_close_matches(key(name), sorted(self.known), n=3, cutoff=.60)
            candidates = sorted({x for n in nearest for x in self.known[n]})
            hint = ' Suggestions: ' + ', '.join(n for n, _ in candidates) if candidates else ''
            raise IdentityError('Fighter not found: ' + name + '. Check the spelling.' + hint, candidates)
        if len(matches) > 1:
            raise IdentityError('Ambiguous fighter name: ' + name + '. Choose the correct identity.', sorted(matches), True)
        return next(iter(matches))

def resolve_fighter(name, sex, root=ROOT, fighter_id=None, profiles=None):
    return FighterCatalog(sex, root, profiles).resolve(name, fighter_id)

def validate_matchup(sex, division, fight_date, a, b):
    iso_date(fight_date)
    choices = MEN_DIVISIONS if sex == 'men' else WOMEN_DIVISIONS
    division = division.replace("Women's ", '').strip()
    match = next((v for v in choices if key(v) == key(division)), None)
    if not match:
        raise ValueError('Unsupported division. Choose: ' + ', '.join(choices))
    if a == b or (key(a[0]) == key(b[0]) and a[1] == b[1]):
        raise ValueError('Choose two different fighters.')
    return match
