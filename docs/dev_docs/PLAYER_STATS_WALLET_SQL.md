# Player Stats, Wallet, and Unit Levels

This reference is specific to my local save.
It cross-references the verified entries in
[save_semantics_report.json](save_semantics_report.json) and the recovered
editor routines. It intentionally excludes equipment, artifacts, relics,
materials, and item inventory.

The attached dump has account ID `1`. The SQL below targets that account only.
Run it against a plain SQLite working copy created from the SQL dump, never
against the encrypted `.db` while the game is running. Keep an untouched backup
before importing or changing a dump.

## Confirmed Overview

| Area | Table | Column(s) | Current value(s) in this dump | Evidence and use |
| --- | --- | --- | --- | --- |
| Account selector | `tb_e973c32e29`, `tb_13c52bbaa8`, `tb_957a223c9b` | `c_3536de9619` | `1` | Verified account ID; retain it in every `WHERE` clause. |
| Gold | `tb_e973c32e29` | `c_d1f333420b` | `1009` | Verified Gold balance. |
| Player skill scrolls | `tb_957a223c9b` | `c_418025e253` | `1` on active preset | Verified per-preset balance. |
| Weapon skill scrolls | `tb_957a223c9b` | `c_ac7e41767f` | `3` on active preset | Verified per-preset balance. |
| Special skill scrolls | `tb_957a223c9b` | `c_a9d19edb77` | `0` on active preset | Verified per-preset balance. |
| Main character | `tb_13c52bbaa8` | `c_d79538c3b8 = 0`, `c_9398111a4b = 1` | One row | Verified selector for the account's main character. |
| Main-character level | `tb_13c52bbaa8` | `c_e3aa3bf474` | `26` | Verified level; editor-enforced valid range is `1` to `75`. |
| Active stat preset | `tb_957a223c9b` | `c_1692f32794 = 0`, `c_bc37480bfc = 1` | One row | Verified first/active main-character preset. |
| Unspent stat points | `tb_957a223c9b` | `c_c982c144a0` | `0` | Verified direct value; no storage offset. |
| Strength | `tb_957a223c9b` | `c_7e92e023a5` | `42` displayed | Stored value is displayed value minus `1`. |
| Vitality | `tb_957a223c9b` | `c_1c77e26632` | `26` displayed | Stored value is displayed value minus `1`. |
| Agility | `tb_957a223c9b` | `c_b91b1c4561` | `75` displayed | Stored value is displayed value minus `1`. |
| Intelligence | `tb_957a223c9b` | `c_3cd914b873` | `10` displayed | Stored value is displayed value minus `1`. |
| Perception | `tb_957a223c9b` | `c_795582f14f` | `41` displayed | Stored value is displayed value minus `1`. |
| Unit roster | `tb_13c52bbaa8` | `c_d4f6740b9b`, `c_9398111a4b`, `c_e3aa3bf474` | Eight type-`1` rows | `c_d4f6740b9b` is the row ID, `c_9398111a4b` is the unit catalog ID, and `c_e3aa3bf474` is the verified level. |

`tb_e973c32e29` also contains four confirmed scroll-related values, but the
editor's update routine changes the per-preset fields in `tb_957a223c9b`.
Do not write the wallet's scroll-looking columns on their own; change the
per-preset fields below and let the game reconcile its own wallet state.

`T_CLIENTINFO` is an older-looking table but has no rows in this dump, so it is
not an active player-stat source. The unmapped `c_*` wallet fields are also
deliberately excluded.

## Read-Only Checks

Run these first after importing the `.sql` dump into a plain SQLite database:

```sql
SELECT
  r.c_e3aa3bf474 AS main_character_level,
  p.c_c982c144a0 AS unspent_stat_points,
  p.c_7e92e023a5 + 1 AS strength,
  p.c_1c77e26632 + 1 AS vitality,
  p.c_b91b1c4561 + 1 AS agility,
  p.c_3cd914b873 + 1 AS intelligence,
  p.c_795582f14f + 1 AS perception
FROM tb_13c52bbaa8 AS r
JOIN tb_957a223c9b AS p ON p.c_d4f6740b9b = r.c_d4f6740b9b
WHERE r.c_3536de9619 = 1
  AND r.c_d79538c3b8 = 0
  AND r.c_9398111a4b = 1
  AND p.c_1692f32794 = 0
  AND p.c_bc37480bfc = 1;

SELECT
  c_d1f333420b AS gold,
  c_418025e253 AS wallet_player_skill_scrolls,
  c_ac7e41767f AS wallet_weapon_skill_scrolls,
  c_a9d19edb77 AS wallet_special_skill_scrolls,
  c_8ecb8b7c8e AS wallet_identity_skill_scrolls
FROM tb_e973c32e29
WHERE c_3536de9619 = 1;

SELECT
  c_d4f6740b9b AS roster_row_id,
  c_d79538c3b8 AS roster_record_type,
  c_9398111a4b AS unit_catalog_id,
  c_e3aa3bf474 AS level
FROM tb_13c52bbaa8
WHERE c_3536de9619 = 1
ORDER BY c_d79538c3b8, c_9398111a4b;
```

## Copy-Ready Update Transactions

Each block is independent. Change the target values before running it, then
verify with the read-only checks and launch the game once before making another
change.

### Gold

```sql
BEGIN IMMEDIATE;

UPDATE tb_e973c32e29
SET c_d1f333420b = 999999
WHERE c_3536de9619 = 1;

COMMIT;
```

### Main-Character Level

The recovered editor limits valid levels to `1` through `75`; no separate XP
column was identified for this edit.

```sql
BEGIN IMMEDIATE;

UPDATE tb_13c52bbaa8
SET c_e3aa3bf474 = 75
WHERE c_3536de9619 = 1
  AND c_d79538c3b8 = 0
  AND c_9398111a4b = 1;

COMMIT;
```

### Core Stats and Unspent Points

The targets in the CTE are **displayed in-game values**. Each core stat is
stored as target minus one; unspent points are stored directly.

```sql
BEGIN IMMEDIATE;

WITH target AS (
  SELECT
    1 AS account_id,
    100 AS strength,
    100 AS vitality,
    100 AS agility,
    100 AS intelligence,
    100 AS perception,
    250 AS unspent_points
)
UPDATE tb_957a223c9b
SET
  c_7e92e023a5 = (SELECT strength - 1 FROM target),
  c_1c77e26632 = (SELECT vitality - 1 FROM target),
  c_b91b1c4561 = (SELECT agility - 1 FROM target),
  c_3cd914b873 = (SELECT intelligence - 1 FROM target),
  c_795582f14f = (SELECT perception - 1 FROM target),
  c_c982c144a0 = (SELECT unspent_points FROM target)
WHERE c_3536de9619 = (SELECT account_id FROM target)
  AND c_1692f32794 = 0
  AND c_bc37480bfc = 1;

COMMIT;
```

### Player, Weapon, and Special Skill Scrolls

These balances are per preset. This updates every preset for account `1`, which
matches the recovered editor's behavior. Identity scrolls are excluded because
the editor derives their useful maximum from the preset's awakened skills.

```sql
BEGIN IMMEDIATE;

UPDATE tb_957a223c9b
SET
  c_418025e253 = 99,
  c_ac7e41767f = 99,
  c_a9d19edb77 = 99
WHERE c_3536de9619 = 1;

COMMIT;
```

### One Unit's Level

First copy the intended unit's `roster_row_id` from the unit listing query.
Keep the level in the verified range `1` through `75`.

```sql
BEGIN IMMEDIATE;

UPDATE tb_13c52bbaa8
SET c_e3aa3bf474 = 75
WHERE c_3536de9619 = 1
  AND c_d4f6740b9b = 878581778149818369;

COMMIT;
```

### All Existing Hunter Units

In this dump, roster record type `1` is the eight existing hunter-unit rows.
Run the unit listing query first; do not apply this to any future, unverified
record type.

```sql
BEGIN IMMEDIATE;

UPDATE tb_13c52bbaa8
SET c_e3aa3bf474 = 75
WHERE c_3536de9619 = 1
  AND c_d79538c3b8 = 1;

COMMIT;
```

## Do Not Change Here

Do not edit the roster primary key (`c_d4f6740b9b`), account ID,
`c_9398111a4b` catalog IDs, `c_1692f32794` preset indexes, timestamps, or
unmapped `c_*` fields. Those values are identifiers, selectors, bookkeeping, or
not yet semantically verified. Equipment and inventory tables are outside this
document's scope.
