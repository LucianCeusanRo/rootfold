---
id: microwave-fade
title: Microwave fade / RSL low
summary: Last-mile or backbone radio hop with a fade or low received-signal level.
match:
  names:
    - Microwave hop down
    - RSL low
    - Microwave fade
  keywords:
    - microwave
    - rsl
    - fade
    - radio hop
  media:
    - microwave
checks:
  - Ping / ICMP to the far end
  - Checked the maintenance calendar
  - Looked at recent changes
  - Compared current RSL / SNR with the baseline
  - Checked weather / fading conditions on the path
---

# Microwave fade / RSL low

A microwave hop can drop without a fibre cut: rain, ducting, antenna alignment or a radio alarm will all look like "site down" from the far end.

## What to do

1. Confirm the alert is on a **microwave** circuit, not a fibre span that happens to sit behind it.
2. Ping the far-end management address. If the near end answers and the far end does not, the hop itself is the suspect.
3. Open the maintenance calendar. A planned radio swap or realignment should already have a window.
4. Look at recent changes (config, firmware, antenna work).
5. Compare **RSL / SNR** with the commissioning baseline. A sudden deep fade is weather or alignment; a slow walk is more often equipment.
6. If the hop carries a customer, say so in the L1 notes and set impact honestly.

## What not to do

Do not resolve the parent incident until the far end is reachable again *and* any leftover child (for example a backup job) has a fresh OK.
