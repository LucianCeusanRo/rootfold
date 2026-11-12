---
id: lacp-bundle-down
title: LACP bundle down
summary: The whole LAG/LACP bundle is down; all members are failed or the aggregate is admin-down.
match:
  names:
    - LACP bundle down
    - LAG down
    - Bundle down
  keywords:
    - lacp bundle
    - lag down
    - bundle down
    - aggregate down
checks:
  - Ping / ICMP to the far end
  - Confirmed every member of the bundle is down or the aggregate is admin-down
  - Checked the maintenance calendar
  - Looked at recent changes
  - Checked whether a parent fibre / microwave span is the real cause
---

# LACP bundle down

The aggregate itself is down. Either every member failed, or someone shut the bundle. This can take a PoP off the air if it was the only uplink.

## What to do

1. List the members and their individual state. One member still up means you may be looking at a stale bundle alarm.
2. Check whether a **parent circuit** (fibre or microwave) is already firing — the bundle alarm may be a symptom.
3. Maintenance calendar and recent changes (lag reconfiguration is a frequent cause).
4. Set impact honestly: if the site is unreachable, `site-down`; if a redundant path is carrying traffic, `degraded`.

## What not to do

Do not flap remaining unrelated uplinks. Fold this under the highest firing parent if Rootfold has already correlated it.
