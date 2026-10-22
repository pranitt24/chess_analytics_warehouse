# Data profile (Phase B)

Streamed the first 20000 games of each sampled month. These are the first hours of the month's first day, so this shows **field availability**, not the month's overall distribution.

## Header availability (% of sampled games that contain the header)

| Header | 2013-01 | 2014-01 | 2015-01 | 2016-01 | 2017-01 | 2018-01 | 2018-02 |
|---|---|---|---|---|---|---|---|
| Event | 100% | 100% | 100% | 100% | 100% | 100% | 100% |
| Site | 100% | 100% | 100% | 100% | 100% | 100% | 100% |
| Date | 0% | 0% | 0% | 0% | 0% | 0% | 0% |
| UTCDate | 100% | 100% | 100% | 100% | 100% | 100% | 100% |
| UTCTime | 100% | 100% | 100% | 100% | 100% | 100% | 100% |
| White | 100% | 100% | 100% | 100% | 100% | 100% | 100% |
| Black | 100% | 100% | 100% | 100% | 100% | 100% | 100% |
| Result | 100% | 100% | 100% | 100% | 100% | 100% | 100% |
| WhiteElo | 100% | 100% | 100% | 100% | 100% | 100% | 100% |
| BlackElo | 100% | 100% | 100% | 100% | 100% | 100% | 100% |
| WhiteRatingDiff | 100% | 99% | 98% | 100% | 100% | 100% | 100% |
| BlackRatingDiff | 100% | 99% | 98% | 100% | 100% | 100% | 100% |
| WhiteTitle | 0% | 0% | 0% | 1% | 1% | 0% | 1% |
| BlackTitle | 0% | 0% | 0% | 1% | 1% | 0% | 1% |
| ECO | 100% | 100% | 100% | 100% | 100% | 100% | 100% |
| Opening | 100% | 100% | 100% | 100% | 100% | 100% | 100% |
| TimeControl | 100% | 100% | 100% | 100% | 100% | 100% | 100% |
| Termination | 100% | 100% | 100% | 100% | 100% | 100% | 100% |
| Variant | 0% | 0% | 0% | 0% | 0% | 0% | 0% |

## Move annotations

| Month | Games with `%clk` | Games with `%eval` |
|---|---|---|
| 2013-01 | 0% | 1% |
| 2014-01 | 0% | 4% |
| 2015-01 | 0% | 17% |
| 2016-01 | 0% | 15% |
| 2017-01 | 0% | 12% |
| 2018-01 | 100% | 8% |
| 2018-02 | 100% | 8% |

## Distributions

### 2013-01  (n=20000)

- Time-control category: Blitz 37%, Rapid 32%, Bullet 28%, Classical 2%, none/- 0%
- Termination: Normal 67%, Time forfeit 33%
- Result: 1-0 51%, 0-1 46%, 1/2-1/2 3%
- Event type: Blitz 37%, Classical 35%, Bullet 28%, Correspondence 0%
- Plies per game: median 62, mean 65.9, share under 10 plies 3%
- Elo: min 800, median 1590, max 2374

### 2014-01  (n=20000)

- Time-control category: Blitz 37%, Rapid 32%, Bullet 27%, Classical 3%, none/- 0%
- Termination: Normal 68%, Time forfeit 32%
- Result: 1-0 51%, 0-1 45%, 1/2-1/2 3%
- Event type: Blitz 37%, Classical 35%, Bullet 27%, Correspondence 0%
- Plies per game: median 63, mean 66.8, share under 10 plies 2%
- Elo: min 814, median 1626, max 2455

### 2015-01  (n=20000)

- Time-control category: Blitz 45%, Rapid 27%, Bullet 26%, Classical 2%, none/- 0%
- Termination: Normal 65%, Time forfeit 33%, Abandoned 1%, Rules infraction 0%
- Result: 1-0 51%, 0-1 46%, 1/2-1/2 4%
- Event type: Blitz 45%, Classical 28%, Bullet 26%, Correspondence 0%
- Plies per game: median 63, mean 65.8, share under 10 plies 4%
- Elo: min 798, median 1632, max 2618

### 2016-01  (n=20000)

- Time-control category: Bullet 40%, Blitz 38%, Rapid 20%, Classical 2%, none/- 0%
- Termination: Normal 64%, Time forfeit 35%, Abandoned 1%
- Result: 1-0 50%, 0-1 47%, 1/2-1/2 4%
- Event type: Bullet 40%, Blitz 38%, Classical 22%, Correspondence 0%
- Plies per game: median 62, mean 65.9, share under 10 plies 2%
- Elo: min 787, median 1719, max 2593

### 2017-01  (n=20000)

- Time-control category: Blitz 46%, Bullet 29%, Rapid 24%, Classical 2%, none/- 0%
- Termination: Normal 68%, Time forfeit 32%, Abandoned 1%, Rules infraction 0%, Unterminated 0%
- Result: 1-0 49%, 0-1 46%, 1/2-1/2 4%, * 0%
- Event type: Blitz 46%, Bullet 29%, Classical 25%, Correspondence 0%
- Plies per game: median 64, mean 67.7, share under 10 plies 2%
- Elo: min 780, median 1700, max 2834

### 2018-01  (n=20000)

- Time-control category: Blitz 48%, Bullet 35%, Rapid 15%, Classical 2%, none/- 0%
- Termination: Normal 64%, Time forfeit 35%, Abandoned 0%, Unterminated 0%
- Result: 1-0 50%, 0-1 47%, 1/2-1/2 4%, * 0%
- Event type: Blitz 48%, Bullet 32%, Standard 15%, UltraBullet 3%, Classical 2%, Correspondence 0%
- Plies per game: median 63, mean 66.9, share under 10 plies 1%
- Elo: min 776, median 1634, max 2671

### 2018-02  (n=20000)

- Time-control category: Blitz 48%, Bullet 34%, Rapid 15%, Classical 2%, none/- 0%
- Termination: Normal 65%, Time forfeit 35%, Abandoned 0%, Unterminated 0%, Rules infraction 0%
- Result: 1-0 50%, 0-1 47%, 1/2-1/2 4%, * 0%
- Event type: Blitz 48%, Bullet 32%, Standard 15%, Classical 2%, UltraBullet 2%, Correspondence 0%
- Plies per game: median 64, mean 67.4, share under 10 plies 1%
- Elo: min 800, median 1602, max 2751

## Which features are usable, per year

| Year | Month sampled | Clock timing features | Embedded evals | Termination | Rating diffs | ECO/Opening |
|---|---|---|---|---|---|---|
| 2013 | 2013-01 | no (0%) | some (1%) | yes | yes | yes |
| 2014 | 2014-01 | no (0%) | some (4%) | yes | yes | yes |
| 2015 | 2015-01 | no (0%) | some (17%) | yes | yes | yes |
| 2016 | 2016-01 | no (0%) | some (15%) | yes | yes | yes |
| 2017 | 2017-01 | no (0%) | some (12%) | yes | yes | yes |
| 2018 | 2018-01 | yes (100%) | some (8%) | yes | yes | yes |
| 2018 | 2018-02 | yes (100%) | some (8%) | yes | yes | yes |
