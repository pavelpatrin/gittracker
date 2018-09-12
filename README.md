# WTF? Who touched my code???

Its simple to answer!

```bash
python3.6 -m gittracker \
    --repopath ../../target-web \
    --remote origin \
    --pattern 'trg-[\d]+' \
    --email p.patrin@gmail.com
```