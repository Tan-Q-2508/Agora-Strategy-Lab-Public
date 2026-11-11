"""The lab: Claude's research sprints inside Agora (Phase 25, D-143).

Claude Code can't run inside Agora (that needs a paid API), but in a session on the user's
laptop it can do strategy research with his real data and leave the results behind as a
tested playbook. This package is the bench it works at: strategy families with an economic
reason (``families``), a headless runner on the shared engine (``runner``), a ledger of every
test (``ledger``), a sealed vault of recent history (``vault``), and the playbook that Metis
and Kairos read (``playbook``). Nothing here places an order or needs the network.
"""
