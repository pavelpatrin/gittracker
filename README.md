# WTF? Who touched my code???

Its simple to answer!

```bash
# Simple usage
python3.6 gittracker.py \
    --repopath ../../target-web

# Advanced usage
python3.6 gittracker.py \
    --repopath ../../target-web \
    --remote origin \
    --users p.patrin@gmail.com \
    --branches 'trg-[\d]+' \
    --files '.*\.py$' \
    --after-date '2018-09-01' \
    --logging DEBUG \
    > log.log
```