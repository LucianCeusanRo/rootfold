---
id: high-crc-errors
title: High CRC / interface errors
summary: A link is up but is incrementing CRC, input errors or FCS errors.
match:
  names:
    - High CRC
    - CRC errors
    - Interface errors
    - FCS errors
    - Input errors
  keywords:
    - crc
    - fcs
    - input errors
    - interface errors
    - symbol errors
checks:
  - Checked error counters and whether they are still incrementing
  - Looked at recent changes
  - Checked optics / cable / patching at both ends
  - Confirmed whether customers are seeing packet loss or only a counter alarm
  - Checked the maintenance calendar
---

# High CRC / interface errors

The interface is usually still *up*. CRC / FCS / input errors mean frames are arriving corrupted: dirty fibre, a bad patch, a failing optic, duplex mismatch, or a weak microwave.

## What to do

1. Confirm the counters are **still incrementing**, not a historical bump.
2. Check whether customers are actually seeing loss. A noisy but unused interface is not `customer-impact`.
3. Inspect optics and patching at both ends before swapping hardware.
4. On a microwave, correlate with RSL / SNR — errors often track a fade.
5. Record the counter values and time in the L1 notes so the next shift can see the trend.

## What not to do

Do not bounce a production bundle "to clear the errors" without a window and a senior eye. The errors will come back if the physical path is bad.
