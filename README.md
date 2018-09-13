# WTF? Who touched my code???

Its simple to answer!

```bash
python3.6 -m gittracker \
    --repopath ../../target-web \
    --remote origin \
    --users p.patrin@corp.mail.ru \
    --branches 'trg-[\d]+' \
    --files '.*\.py$'
```