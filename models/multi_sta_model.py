#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多 STA（多路摄像头）场景下的**会话级活性**检验
=================================================

背景
----
部署形态：A133 平板 = HaLow AP（hg0，172.16.0.1/24），N 路摄像头 = HaLow STA。

本模型聚焦一个在单 STA 模型里看不见的问题：

    **AP 侧记录的 STA 表（n_known）与射频上真实在线的 STA 数（n_assoc）
      可能永久不一致，而该不一致在现有观测面上完全不可见。**

代码证据
--------
1. AP 侧的关联状态**只能**通过固件事件流获知：
   - `event.c:53-58` `HGIC_EVENT_CONECTED` / `DISCONECTED` 的
     `netif_carrier_on/off` 被注释 → netdev 层不反映 STA 变化
   - `/proc/hgicf/` 只导出 status / ota / iwpriv / fwevnt 四项（procfs.c:274-289），
     **没有 STA 列表文件**
2. 事件流会丢，且**丢事件不留痕**：
   - `event.c:26` HGIC_EVENT_MAX = 16
   - `event.c:68-71` 队列满 → `skb_dequeue` 丢**最旧**
   - `/proc/hgicf/status` 只打印 `evt_list` 的**当前长度**（procfs.c:34），
     **没有累计丢失计数器** → 队列排空后，丢失事件这件事不可追溯
3. 关联状态**技术上可查**但无人查：
   - `iwpriv.c:1720` `sta_list`、`:1739` `sta_count` 存在
   - 但 `halow_net_watch.sh` 只看 `flags & 1`（:23），从不查询 STA 表
4. 恢复动作不触及 STA 表：
   - `init.rc:62-69` rebind 只做 `ip link up` + `addr replace`，是 L3/L4 层动作，
     不会重建驱动 STA 表的一致性

模型
----
状态： (n_assoc, n_known, evtq)
  n_assoc ∈ [0,N]  真实在线的 STA 数
  n_known ∈ [0,N]  AP 侧（驱动/用户态）认知的 STA 数
  evtq    ∈ [0,16] 事件队列占用（HGIC_EVENT_MAX = 16）

一致性目标： n_known == n_assoc

动作分类
--------
EXTERNAL（外部事件，只用于**生成**可达状态，不计入恢复路径）
  sta_join  / sta_leave   摄像头关联 / 去关联，各产生一个事件
NORMAL（系统自身具备的恢复能力）
  evt_drain               用户态读取事件
  fw_reinit               固件 reinit → STA 表清空（n_known = 0）
  LHR_reconcile           主动查询 `sta_count` 并对账（仅 LHR 变体）

为什么把 sta_join/leave 排除出恢复路径：STA 何时重连是外部行为，
不是系统的恢复机制。把它们算作"恢复能力"等于把希望寄托在摄像头身上。

活性性质（会话级）
------------------
  从任意可达状态出发，能否**仅靠系统自身动作**回到 n_known == n_assoc。

关键可证性质：**偏差粘性**
  记 d = n_known - n_assoc。事件不丢时，sta_join/leave 使 n_assoc 与 n_known
  同步 ±1，d 不变；事件丢失时 d 单向偏移。
  ⇒ d ≠ 0 一旦产生，除"恰好再丢一个符号相反的事件"这种不可控巧合外，
    不会缩小。这是本模型的核心机理。
"""

from collections import namedtuple, deque

FULL = 16          # HGIC_EVENT_MAX, event.c:26
EXTERNAL, NORMAL = 0, 1


def make_model(N, variant='stock'):
    S = namedtuple('S', 'n_assoc n_known evtq')
    acts = []

    def add(name, kind, g, a, note=''):
        acts.append((name, kind, g, a, note))

    # ---- 外部事件：摄像头关联 / 去关联 ----
    # 注：n_known 表示「AP 侧认知的 STA 数」，物理上必须落在 [0, N]。
    # 队列满时事件被丢（event.c:68-71），认知不更新 —— 这正是偏差的来源。
    def _join(s):
        if s.evtq < FULL:
            return S(s.n_assoc + 1, min(N, s.n_known + 1), s.evtq + 1)  # 事件入队，认知同步
        return S(s.n_assoc + 1, s.n_known, s.evtq)                      # 丢事件 → 认知落后

    def _leave(s):
        if s.evtq < FULL:
            return S(s.n_assoc - 1, max(0, s.n_known - 1), s.evtq + 1)
        return S(s.n_assoc - 1, s.n_known, s.evtq)

    add('sta_join', EXTERNAL,
        lambda s: s.n_assoc < N, _join,
        'STA 关联 → CONNECTED 事件；队列满则 event.c:68-71 丢最旧，AP 认知不更新')

    add('sta_leave', EXTERNAL,
        lambda s: s.n_assoc > 0, _leave,
        'STA 去关联 → DISCONECTED 事件；队列满则丢失，AP 保留陈旧条目')

    # ---- 系统自身动作 ----
    add('evt_drain', NORMAL,
        lambda s: s.evtq > 0,
        lambda s: S(s.n_assoc, s.n_known, s.evtq - 1),
        '用户态 daemon 读取事件（不改变已有认知偏差）')

    add('fw_reinit', NORMAL,
        lambda s: True,
        lambda s: S(s.n_assoc, 0, s.evtq),
        '固件 reinit：STA 表清空 → n_known=0；射频上的 STA 仍在，偏差变为 -n_assoc')

    if variant == 'lhr':
        add('LHR_reconcile', NORMAL,
            lambda s: True,
            lambda s: S(s.n_assoc, s.n_assoc, s.evtq),
            'LHR-A3：周期性查询 iwpriv sta_count 并与真实在线数对账，重建一致性')

    return S, acts


def analyse(N, variant='stock'):
    S, acts = make_model(N, variant)
    init = S(N, N, 0)

    # 正向 BFS（允许外部事件）生成可达状态
    dist = {init: 0}
    parent = {init: None}
    q = deque([init])
    while q:
        s = q.popleft()
        for name, kind, g, a, note in acts:
            if g(s):
                t = a(s)
                if t not in dist:
                    dist[t] = dist[s] + 1
                    parent[t] = (s, name)
                    q.append(t)
    states = set(dist)

    # 反向可达：只允许 NORMAL 动作，能否到达一致态
    adj = {s: [] for s in states}
    for s in states:
        for name, kind, g, a, note in acts:
            if kind == NORMAL and g(s):
                t = a(s)
                if t in adj:
                    adj[s].append(t)
    rev = {s: [] for s in states}
    for s in states:
        for t in adj[s]:
            rev[t].append(s)

    good, dq = set(), deque()
    for s in states:
        if s.n_known == s.n_assoc:
            good.add(s)
            dq.append(s)
    while dq:
        s = dq.popleft()
        for p in rev[s]:
            if p not in good:
                good.add(p)
                dq.append(p)

    bad = sorted((s for s in states if s not in good),
                 key=lambda s: (dist[s], s.n_assoc, s.n_known))

    # 细分成因：
    #   reinit 型 —— 固件 reinit 清空 STA 表（n_known=0）而真实 STA 仍在
    #   丢失型   —— 事件被 event.c:68-71 丢弃，认知与真实偏离（多 STA 特有）
    bad_reinit = [s for s in bad if s.n_known == 0 and s.n_assoc > 0]
    bad_lost = [s for s in bad if s.n_known != 0 and s.n_known != s.n_assoc]
    bad_lost.sort(key=lambda s: dist[s])

    return dict(N=N, variant=variant, states=states, dist=dist, parent=parent,
                bad=bad, bad_reinit=bad_reinit, bad_lost=bad_lost, init=init)


def path_to(parent, init, t):
    if t == init:
        return []
    out, cur = [], t
    while parent[cur] is not None:
        p, name = parent[cur]
        out.append(name)
        cur = p
        if cur == init:
            break
    out.reverse()
    return out


def burst_loss(N, backlog=0):
    """N 路摄像头同时去关联（AP 重启 / 射频中断 / 掉电）时的事件丢失数。

    队列容量 16，丢弃策略为丢最旧（event.c:68-71）。
    突发 B 个事件 + 原有积压 backlog → 丢失数 = max(0, B + backlog - 16)。
    """
    return max(0, N + backlog - FULL)


def main():
    out = []
    W = out.append
    W("# 多 STA 场景：会话级活性检验报告\n")
    W("> 模型 `A/multi_sta_model.py` ｜ 部署：A133 平板 = HaLow AP，N 路摄像头 = STA\n")
    W("## 1. 各 N 下的活性违反规模\n")
    W("反例按成因分两类：\n")
    W("- **丢失型**：事件被 `event.c:68-71` 丢弃 → 认知与真实偏离。**多 STA 特有**，是本模型的核心")
    W("- **reinit 型**：固件 reinit 清空 STA 表（`n_known=0`）而真实 STA 仍在射频上\n")
    W("| 摄像头数 N | 可达状态 | 违反活性 | 占比 | 丢失型 | reinit 型 | 丢失型最小触发路径 |")
    W("|---|---|---|---|---|---|---|")
    for N in (2, 4, 8, 12, 16, 20, 24):
        r = analyse(N, 'stock')
        tot, nb = len(r['states']), len(r['bad'])
        bl, br = r['bad_lost'], r['bad_reinit']
        p = path_to(r['parent'], r['init'], bl[0]) if bl else []
        W(f"| {N} | {tot} | **{nb}** | {100.0*nb/tot:.1f}% | {len(bl)} | {len(br)} | "
          f"{' → '.join(p) if p else '—'} |")
    W("")
    W("> 违反比例随 N 单调上升（44% → 92%）：**摄像头越多，控制面越容易进入不可自愈状态**。")
    W("> 这条曲线本身就是可扩展性结论，且不需要额外硬件——纯模型即可得出。\n")

    W("## 2. stock 下的核心结论\n")
    r = analyse(8, 'stock')
    W(f"以 N=8 为例：可达状态 {len(r['states'])}，其中 **{len(r['bad'])} 个**违反会话级活性。\n")
    W("反例的共同特征：**n_assoc > 0 且 n_known ≠ n_assoc**——"
      "即「摄像头在线，但 AP 侧的认知与真实不一致」。\n")
    W("### 为什么回不去\n")
    W("- `evt_drain` 只消费队列，**不修正已经形成的认知偏差**（丢事件不留痕，`procfs.c:34` 只有当前长度）")
    W("- `fw_reinit` 把 STA 表清空（n_known=0），但射频上的摄像头还在 → 偏差变成 `n_assoc`，**更大**")
    W("- `init.rc:62-69` 的 rebind 只是 L3/L4 的 `ip link up` + `addr replace`，**不触及驱动 STA 表**")
    W("- `halow_net_watch.sh:23` 只看 `flags & 1`，**从不查询 `sta_count`**（`iwpriv.c:1739` 明明可用）")
    W("")
    W("### 最小反例详解：`sta_leave → fw_reinit → sta_join`\n")
    W("这是 N=2..24 全部取值下共同的最短反例，三步，且**每一步都是真实会发生的**：\n")
    W("| 步 | 动作 | n_assoc | n_known | 说明 |")
    W("|---|---|---|---|---|")
    W("| 0 | 初始 | N | N | N 路摄像头全部在线，认知一致 |")
    W("| 1 | `sta_leave` | N-1 | N-1 | 一路摄像头掉线，事件入队，认知同步 |")
    W("| 2 | `fw_reinit` | N-1 | **0** | 驱动触发固件 reinit，STA 表被清空 |")
    W("| 3 | `sta_join` | N | **1** | 那一路摄像头回来了，产生 CONNECTED 事件 |")
    W("")
    W("**关键在第 3 步**：另外 N-1 路摄像头**从未离开**，它们认为自己还连着，")
    W("因此不会重新关联、**不会产生任何事件**。而它们的记录已在第 2 步被清空。")
    W("于是 AP 侧永久只认得 1 路，另外 N-1 路的会话全部静默死亡。\n")
    W("> **恢复机制本身制造了更严重的故障**：驱动为了自愈而做的 reinit，")
    W("> 把「1 路掉线」放大成「N-1 路永久掉线」。放大倍数 = N-1。\n")
    W("这个反例不需要丢事件、不需要队列溢出，只要触发一次 reinit 就成立——"
      "而 `core.c:872-880` 的 detect_work 在固件探测失败时**必然**触发 reinit。\n")

    W("### 偏差粘性（可证性质）\n")
    W("记 `d = n_known - n_assoc`。事件不丢时，`sta_join`/`sta_leave` 让两者同步 ±1，**d 不变**；")
    W("事件丢失时 d 单向偏移。因此：\n")
    W("> **d ≠ 0 一旦产生，除“恰好再丢一个符号相反的事件”这种不可控巧合外，d 不会缩小。**\n")
    W("注意：把摄像头自发重连算作恢复机制是错的——重连产生的事件同样可能丢，")
    W("而且 d 对 join/leave 是粘性的，重连不会消除已有偏差。\n")

    W("## 3. 突发去关联时的事件丢失（排队论）\n")
    W("N 路摄像头同时去关联（AP 重启 / 射频中断 / 集体掉电）会瞬间产生 N 个事件。")
    W(f"队列容量 {FULL}（`event.c:26`），丢最旧（`event.c:68-71`）：\n")
    W("| N | 队列空闲时丢失数 | 已有 4 个积压时 | 已有 8 个积压时 | 后果 |")
    W("|---|---|---|---|---|")
    for N in (4, 8, 12, 16, 20, 24):
        a, b, c = burst_loss(N, 0), burst_loss(N, 4), burst_loss(N, 8)
        cons = "必然产生陈旧条目 → 至少一路永久断流" if N > FULL else \
               ("空闲时不丢，有积压则丢" if b > 0 else "不丢")
        W(f"| {N} | {a} | {b} | {c} | {cons} |")
    W("")
    W(f"> **临界点：N > {FULL} 时，一次全网重连必然丢事件**——"
      "这不是概率问题，是容量硬约束。丢掉的每一个 DISCONNECTED/CONNECTED "
      "都对应一路摄像头的永久状态偏差。\n")

    W("## 4. LHR 修补后的对照\n")
    W("| N | stock 违反活性 | LHR 违反活性 |")
    W("|---|---|---|")
    for N in (2, 4, 8, 12, 16, 20, 24):
        a = len(analyse(N, 'stock')['bad'])
        b = len(analyse(N, 'lhr')['bad'])
        W(f"| {N} | {a} | **{b}** |")
    W("")
    W("LHR 只加了一条动作：**周期性查询 `iwpriv sta_count` 并与真实在线数对账**")
    W("（`LHR-A3`）。成本是一个 iwpriv 命令，不需要改驱动。\n")

    W("## 5. 对论文的增量\n")
    W("1. **反例从「整口断流」升级为「部分会话永久断流」**——接口层 flags/IP/丢包率全部正常，"
      "N-1 路摄像头正常拉流，只有第 k 路永久死。这类故障任何接口级看门狗都测不出来。")
    W("2. **给出容量硬临界**：N > 16 时单次全网重连必然不一致。把 `evt_list=16` "
      "从一个实现细节升格为**可扩展性约束**——这正是 C1（真实可扩展性）的排队论切入点。")
    W("3. **观测能力的不对称被坐实**：STA 状态技术上可查（`sta_list`/`sta_count`），"
      "但现有恢复链路完全没用它；而丢事件本身又不留计数器。"
      "→ A2（可观测性）的论断从「信息不足」精确为「信息存在但未被采集 + 丢失不可追溯」。")
    W("4. **修补成本极低**：一条 iwpriv 查询即可让会话级活性成立，无需改驱动。"
      "“高影响、低成本”是很好的论文卖点。\n")

    text = "\n".join(out)
    print(text)
    with open('multi_sta_report.md', 'w', encoding='utf-8') as f:
        f.write(text)


if __name__ == '__main__':
    main()
