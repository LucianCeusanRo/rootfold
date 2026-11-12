---
id: vpn-tunnel-down
title: VPN tunnel down
summary: An IPsec or similar VPN tunnel is down or not passing phase-2 traffic.
match:
  names:
    - VPN tunnel down
    - IPsec down
    - Tunnel down
    - VPN down
  keywords:
    - vpn
    - ipsec
    - ike
    - tunnel down
    - phase 2
checks:
  - Ping / ICMP to the far-end tunnel address
  - Checked the maintenance calendar
  - Looked at recent changes (PSK, crypto, peer IP, firewall)
  - Confirmed phase 1 / phase 2 state on both peers if reachable
  - Checked whether the underlay (WAN / fibre / microwave) is the parent cause
---

# VPN tunnel down

A tunnel alarm can be the tunnel itself (PSK, lifetime, firewall) or just the underlay path dying.

## What to do

1. Check the **underlay** first: if the WAN, fibre or microwave to that peer is down, the tunnel is a symptom.
2. If the underlay is up, check phase 1 / phase 2 on both peers and recent crypto or PSK changes.
3. Ping the far-end tunnel address, not only the public peer IP.
4. Record peer IPs, times and error messages in the L1 notes.

## What not to do

Do not reset both sides at once "to clear IKE" on a tunnel that is down because the fibre is cut. Fix or wait for the parent.
