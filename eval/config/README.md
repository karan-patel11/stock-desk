# Eval batch config override

`news_names.json` goes to `~/.stockdesk/config/news_names.json` (or `<STOCKDESK_HOME>/config/`) before the Phase 4
batch. It is used whole in place of the shipped list, so it keeps the 10 shipped names unchanged and adds one per batch
ticker; nothing else differs. ZZZQ has no name on purpose. Every batch run uses this identical file
(`eval/RUNBOOK.md`, step 1).
