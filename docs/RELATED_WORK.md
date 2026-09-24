# Related work matrix (liveness / product stack)

## The gap in one sentence

Existing HaLow literature concentrates on propagation measurements, RAW MAC, and energy. Formal work on protocols and drivers does not cover Android FullMAC host-stack liveness, and traditional Wi-Fi recovery literature does not cover USB IoT FullMAC with property/oneshot integration.

## Matrix

| Category | Representative work | What they do | Difference from this paper |
|----------|---------------------|--------------|----------------------------|
| HaLow measurement | Maudet 2023/2024; Aust CCNC'24; Chounos 2025; Hakim 2025; Xu arXiv'26 | Field tests of range, throughput, energy, monitoring | No host control-plane liveness |
| HaLow MAC/RAW | Ahmed 2021 survey; Guedes 2026 RAW survey | RAW/grouping theory and simulation | Not product FullMAC failures |
| Protocol model checking | Holzmann SPIN; Lamport TLA+; wireless protocol MC series | Protocol correctness | Not aimed at the Android + USB FMAC combination |
| Linux Wi-Fi recovery | cfg80211 reconnect / rfkill practice and kernel docs | SoftMAC reconnection | Not HaLow USB FullMAC |
| Android network availability | 2.4/5 GHz Wi-Fi availability, doze studies | Not an 802.11ah module stack | Different band and driver model |
| Distributed out-of-band management | Classic out-of-band management; control plane / data plane separation | Same principle | This paper gives a concrete HaLow USB `ready` instance |

## References (draft Bib entries; check against the final .bib before submission)

1. IEEE Std 802.11ah-2016 (HaLow).
2. Ahmed et al., "MAC protocols for IEEE 802.11ah-based IoT," IEEE Internet of Things Journal, 2021.
3. Maudet et al., "Practical evaluation of Wi-Fi HaLow," Internet of Things, 2023.
4. Maudet et al., energy consumption, IEEE Internet of Things Journal, 2024.
5. Kane et al., HaLow vs LoRa, Sensors, 2023.
6. Chounos et al., 802.11ah testbed, 2025.
7. Guedes et al., RAW survey, Wireless Networks, 2026.
8. Hakim et al., HaLow surveillance LOS/NLOS, 2025.
9. Xu et al., long-range monitoring, arXiv, 2026.
10. Holzmann, *The SPIN Model Checker*.
11. Lamport, *Specifying Systems* (TLA+).
12. Linux wireless / cfg80211 documentation (reconnect paths).

## Positioning sentence

> Unlike prior HaLow studies that characterize PHY/MAC performance on SoftMAC modules or simulations, we prove liveness failures of a commercial USB FullMAC + Android host control plane, and validate self-heal boolean outcomes on device without custom firmware.
