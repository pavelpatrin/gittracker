# WTF? Who touched my code???

Its simple to answer!

```bash
# Simple usage
python3.6 gittracker.py \
    --repopath ../../webrepo

# Faster usage
python3.6 gittracker.py \
    --repopath ../../webrepo
    --greenlets 8

# Advanced usage
python3.6 gittracker.py \
    --repopath ../../webrepo \
    --remote origin \
    --owners p.patrin@gmail.com \
    --branches 'trg-[\d]+' \
    --files '.*\.py$' \
    --after-date '2018-09-01' \
    --before-date '2018-09-02' \
    --logging DEBUG \
    > log.log
```
