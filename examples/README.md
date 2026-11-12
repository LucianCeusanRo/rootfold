# Example topology — Carpathian Carrier (lab)

Eleven fictional sites in Moldova (Bacău DC and metro, Onești, Dărmănești, Comănești, Târgu Ocna, Adjud, Focșani, Roman, Piatra Neamț, Bicaz). Fiber backbone plus microwave last-mile hops, an LACP bundle on the core, and one customer access circuit.

**This is not a real network.** It exists so Rootfold can be demonstrated and tested honestly.

The recovery-sweep scenario uses `cir-ons-drm-mw` (Onești—Dărmănești microwave) as the parent, site devices at Dărmănești as children, and `drm-backup` as the leftover child that is still down after the hop recovers.

CSV equivalents can be imported from a directory (`sites.csv`, `devices.csv`, `circuits.csv`, `bundles.csv`, `dependencies.csv`). See `docs/LEARN.md`.
