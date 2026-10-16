# Upgrading to the local v0.7 candidate

Extract the complete new portable into a separate writable folder. Keep `app`,
`runtime` and the EXE together. Use Help → Import from previous installation to
review saved reports and optional preferences; existing originals remain intact,
and import can be undone. Calculation caches and fitted model binaries are not
imported.

Old results keep their original dates, probabilities, policy and captured facts.
They remain viewable/exportable. Changed policy, source or data prevents reuse
for a new calculation. Reports without an evidence-quality block explicitly say
it was not recorded; they are not filled from today's data.

Women's new policy changes training, calibration and ensemble weights. A changed
probability is expected. The inherited numerical reliability grade is withheld:
its thresholds were not validated for this policy. Men's v3 arithmetic is
preserved; the numeric preparation optimization was checked independently.

Both datasets reach 10 October 2026. The refresh adds 22 men's bouts and four
women's bouts, including one draw. Draws remain in history and stay outside
binary training. The broader evaluation used the separate September snapshot,
so “Data differs from evaluated snapshot” is expected on this installation.
Methodology status and snapshot compatibility are separate facts.

Source users need the matching 15 files from the v0.7 portable and the pinned
runtime dependencies. Do not mix a newer manifest with an older release's data.
The release contains no standalone dataset archive.

This is a local experimental candidate, not a published v0.7 or verified stable
release. Clean Windows 10/11 and actual 100/150/200% display-scale checks remain
outstanding because test environments are unavailable. Dataset rights remain
`review_required`; the launcher is unsigned.
