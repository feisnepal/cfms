"""Self-contained CFMG production-water gear rule test suites.

Each gear test file is fully runnable with plain pytest (no database): a small
shared engine (`_cfmg_rules`) evaluates per-item rule indicators so the tests
focus on rule coverage: rate / ratio / tally / TFC / class / offset / digit /
word (Nepali) / TFC / mixed / no-inventory / no-quoted / empty variants across
every category the gear exposes.
"""