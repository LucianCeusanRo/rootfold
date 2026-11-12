---
id: lacp-member-down
title: LACP member down
summary: One member of a LAG/LACP bundle is down; the bundle may still be forwarding.
match:
  names:
    - East member down
    - West member down
    - LACP member down
    - LAG member down
  keywords:
    - lacp member
    - lag member
    - member down
    - bundle member
checks:
  - Confirmed the bundle is still up on the remaining member(s)
  - Checked the maintenance calendar
  - Looked at recent changes
  - Identified which physical member and optic / cable is down
  - Checked errors and light levels on the failed member
---

# LACP member down

One member of an LACP bundle failed. If the other member is still up, the PoP should not go dark — this is a loss of redundancy, not necessarily a site outage.

## What to do

1. Confirm the **bundle** status, not only the member interface.
2. If traffic is still flowing, set impact to `degraded` (or `no-customer-impact` if a lab/test bundle) rather than `site-down`.
3. Identify the physical member (cable, optic, port) and check errors / Rx power.
4. Check maintenance and recent changes (a one-sided shutdown during a swap is common).
5. Do not shut the remaining member to "force a reconverge" unless a runbook or senior engineer says so.

## What not to do

Do not treat a single member failure as a total PoP outage. Rootfold should not promote one member to the bundle until every member is down.
