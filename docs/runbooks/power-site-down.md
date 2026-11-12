---
id: power-site-down
title: Power / site down
summary: A whole site is unreachable, often because of power, and every device behind it is alarming.
match:
  names:
    - Site down
    - Power down
    - Mains fail
    - UPS critical
    - Generator fail
  keywords:
    - power
    - mains
    - ups
    - rectifier
    - generator
    - site down
    - environmental
checks:
  - Confirmed which devices at the site still answer (if any)
  - Checked the maintenance calendar
  - Looked at recent changes
  - Checked power / environmental alarms (mains, UPS, rectifier, generator)
  - Listed customers and downstream sites in the blast radius
---

# Power / site down

When a site goes dark, the NMS will also fire every router, switch and customer circuit behind it. Treat those as symptoms of the site, not as separate root causes.

## What to do

1. Confirm the blast radius: which sites and customers sit behind this one.
2. See whether *any* management address at the site still answers — a single reachable UPS or out-of-band modem changes the picture.
3. Check power and environmental alarms (mains fail, UPS, rectifier, generator).
4. Maintenance calendar (a planned generator test should already have a window).
5. Set impact to `site-down` if the site is dark, and name the downstream customers in the notes.

## What not to do

Do not open a separate ticket for every child alarm, and do not resolve the site when the uplink returns if a leftover child (power at a cabinet, a backup job) still has no fresh OK.
