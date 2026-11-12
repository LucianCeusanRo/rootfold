---
id: fiber-los
title: Fiber LOS
summary: Loss of signal on a fibre span between two sites.
match:
  names:
    - Fiber LOS
    - LOS
    - Fibre LOS
    - Link down
  keywords:
    - los
    - fiber
    - fibre
    - optical
    - light out
  media:
    - fiber
checks:
  - Ping / ICMP to the far end
  - Checked the maintenance calendar
  - Looked at recent changes
  - Confirmed LOS / light levels at both ends
  - Checked whether a customer or vendor ticket is already open
---

# Fiber LOS

Loss of Signal on a fibre span usually means a cut, a dirty or unplugged connector, or a failed optic. Everything behind the span will alarm as a symptom.

## What to do

1. Identify the **span** (A-end and Z-end sites) and list the blast radius — sites, devices, customers behind it.
2. Ping both ends. The near-end device should still be reachable if the failure is on the span itself.
3. Check the maintenance calendar for a planned splice or cable relocation.
4. Confirm optics: LOS, no light, or a sudden drop in Rx power.
5. If this is a leased circuit, open or attach the vendor ticket and put the ID in the L1 notes.
6. Do not spend time bouncing every access switch behind the span until the parent is identified.

## What not to do

Do not close every child ticket the moment the fibre returns. Wait for the recovery sweep and a fresh OK on each child.
