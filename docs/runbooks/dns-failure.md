---
id: dns-failure
title: DNS failure
summary: A resolver, authoritative name server, or DNS forwarding path is failing.
match:
  names:
    - DNS failure
    - DNS down
    - Resolver down
    - SERVFAIL
  keywords:
    - dns
    - resolver
    - servfail
    - nxdomain storm
    - name server
checks:
  - Confirmed the failure with a direct query (dig / nslookup) to the affected server
  - Checked the maintenance calendar
  - Looked at recent changes (zone, forwarding, ACLs)
  - Checked whether this is recursive, authoritative, or a forwarding-only path
  - Checked whether a parent site / VPN / WAN outage is the real cause
---

# DNS failure

People will describe this as "the internet is down". Check DNS itself before you chase every application.

## What to do

1. Query the affected server directly (`dig @server hostname`). Note SERVFAIL vs timeout vs NXDOMAIN.
2. If the server does not even answer ICMP or TCP/53, look at the **site, VPN or WAN** parent first.
3. If it answers but SERVFAILs, look at zone freshness, forwarding, and recent ACL or config changes.
4. Write the exact query, server and response in the L1 notes. "DNS is down" is not enough for L2.

## What not to do

Do not flush caches or restart a shared resolver as a first step on a production server without a check of the parent path and a note to the incoming shift.
