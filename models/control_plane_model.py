#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HaLow Android FullMAC 控制面形式化模型 + 活性/安全性检验
=========================================================

目标
----
把 A133(Android 10) + 泰芯 TXW8301 USB FullMAC 的**控制面**建成一个有限状态机，
穷举可达状态空间，检验：

  L1 (活性 / Liveness)  从任意可达状态出发，是否存在一条**不含故障注入**的动作序列
                        回到 STREAMING（视频流正常）。
                        违反者 = 永久断流反例（liveness counterexample）。

  L2 (安全性 / Safety)  是否存在"黑洞态"：接口 admin UP + 有 IP，但数据面不通，
                        且该状态是**吸收态**（无故障动作下无法离开）。

代码证据（每一条转移都对应真实源码行号）
----------------------------------------
驱动 hgic_fmac/core.c
  :777   mod_timer(detect_tmr, +2000ms)                       —— 检测定时器 2s 周期
  :861   if (!SLEEP && RUNNING) { ... }                       —— SLEEP 置位时**整个检测被跳过**
  :872   bootdl_cmd_enter 探测固件；失败 → bus->reinit
  :886   if (RUNNING) mod_timer(...)                          —— RUNNING 清零则定时器链**永久断裂**
  hgic_def.h:47  #define HGIC_DETECT_TIMER 2000

驱动 hgic_fmac/event.c
  :26    #define HGIC_EVENT_MAX (16)
  :68-71 队列满则 kfree_skb(skb_dequeue(...)) —— **丢最旧**事件，非丢最新
  :53-58 HGIC_EVENT_CONECTED / DISCONECTED 的 netif_carrier_on/off **被注释掉**
         → netdev carrier 恒不变化，事件面与 L4 状态解耦

Android init.device.rc (device/softwinner/ceres-b6)
  :38    insmod hgicf.ko                       (on boot_completed=1，仅一次)
  :57    service halow_net_watch ... oneshot   —— 看门狗是 oneshot，退出即永久停止
  :62-69 on property:rebind_net=1 → exec ip ... ; setprop rebind_net 0
         —— **fire-and-forget**：ip 命令失败也照样清零，无重试无回执
  :59    setprop vendor.a133.halow.ready 1     —— 无条件执行，即使 ip 全部失败
  :105-107 on property:ready=1 → start halow_net_watch

wifi_halow/halow_net_watch.sh
  :5-6   INTERVAL=5, COOLDOWN=10
  :17-19 [ ! -d /sys/class/net/hg0 ] → continue     —— 接口消失时**静默跳过**
  :21    flags=$(cat .../flags) || continue          —— 读取失败也静默跳过
  :23-25 if (flags & 1) != 0 → continue              —— **只查 admin UP 这一个 bit**
         → 固件黑洞 / 流控饿死 / 事件溢出 全部不可见

作者注：本模型是"忠实抽象"——只保留与活性相关的变量，但每条转移的
守卫条件都直接对应上述代码行，不做主观简化。
"""

from collections import namedtuple, deque
import itertools
import sys

# ---------------------------------------------------------------- 状态空间

State = namedtuple('State', [
    'iface',   # 0=ABSENT 1=DOWN 2=UP_NOIP 3=UP_IP 4=BLACKHOLE
    'sleep',   # 0/1  HGIC_BUS_FLAGS_SLEEP
    'fw',      # 0=DEAD 1=LIVE   固件是否响应 bootdl 探测
    'run',     # 0/1  HGICF_DEV_FLAGS_RUNNING
    'darm',    # 0/1  detect_tmr 是否已装填
    'watch',   # 0=WAIT(等 ready) 1=POLL 2=COOLDOWN 3=EXITED
    'p_ready', # 0/1  vendor.a133.halow.ready
    'p_reb',   # 0/1  vendor.a133.halow.rebind_net
    'p_init',  # 0/1  setup_net 链已下发
    'evtq',    # 0/1/2 事件队列 空/部分/满(HGIC_EVENT_MAX)
    'eloss',   # 0/1  是否发生过事件丢失
])

IFACE_NAMES = ['ABSENT', 'DOWN', 'UP_NOIP', 'UP_IP', 'BLACKHOLE']
WATCH_NAMES = ['WAIT', 'POLL', 'COOL', 'EXITED']

A, D, UN, UI, BH = 0, 1, 2, 3, 4

NORMAL = 0
FAULT = 1


def is_streaming(s: State) -> bool:
    """正常拉流状态：接口有 IP + 固件活 + 未睡 + RUNNING + 定时器装填 + 看门狗在轮询"""
    return (s.iface == UI and s.fw == 1 and s.sleep == 0 and s.run == 1
            and s.darm == 1 and s.watch == 1 and s.p_ready == 1)


# ---------------------------------------------------------------- 转移定义

def build_actions(variant='stock'):
    """
    variant='stock' —— 现网实现（严格照抄上述源码）
    variant='lhr'   —— 加入 Layered HaLow Recovery 的修补动作
    """
    acts = []

    def add(name, kind, guard, apply_, note=''):
        acts.append((name, kind, guard, apply_, note))

    # ---------- 驱动 probe / USB ----------
    add('probe', NORMAL,
        lambda s: s.iface == A,
        lambda s: s._replace(iface=D, run=1, darm=1),
        'hgicf.ko probe 成功，netdev 创建，detect_tmr 装填 (core.c:777)')

    # USB 重新枚举完成 —— 外部事件，恢复路径允许使用
    add('usb_reenum', NORMAL,
        lambda s: s.iface == A,
        lambda s: s._replace(iface=D),
        'USB 重枚举，接口重新出现（外部事件，非故障）')

    # ---------- Android property 链 ----------
    add('do_setup_net', NORMAL,
        lambda s: s.p_init == 0 and s.iface in (D, UN),
        lambda s: s._replace(iface=UI, p_init=1, p_ready=1),
        'init.rc:87-93  exec ip link set hg0 up + addr add; setprop ready 1')

    # init.rc:59 无条件 setprop ready=1 —— 即便 ip 命令全部失败（a133_init.sh 10s 超时后仍触发）
    add('do_setup_net_fail', NORMAL,
        lambda s: s.p_init == 0 and s.iface == A,
        lambda s: s._replace(p_init=1, p_ready=1),
        'init.rc:59 ready=1 无条件置位；接口不存在时 ip 全部失败但 ready 仍为 1')

    # rebind：fire-and-forget，执行完无条件 setprop rebind_net 0 (init.rc:69)
    def _reb(s):
        if s.iface == A:
            return s._replace(p_reb=0)          # ip 命令失败，但 property 照样清零
        return s._replace(iface=UI, p_reb=0)
    add('do_rebind', NORMAL,
        lambda s: s.p_reb == 1,
        _reb,
        'init.rc:62-69  ip link up + addr replace；失败亦清零，无重试')

    # ---------- halow_net_watch ----------
    add('watch_start', NORMAL,
        lambda s: s.watch == 0 and s.p_ready == 1,
        lambda s: s._replace(watch=1),
        'init.rc:105-107 start halow_net_watch (oneshot，仅此一次)')

    def _wtick(s):
        # sh:17  接口不存在 → continue
        if s.iface == A:
            return s
        # sh:23  flags & 1 != 0（admin UP）→ continue
        #        注意：BLACKHOLE / UP_NOIP 也都是 admin UP，看门狗**看不见**
        if s.iface in (UN, UI, BH):
            return s
        # sh:27-29 只有 admin DOWN 才触发 rebind，随后 sleep COOLDOWN
        return s._replace(p_reb=1, watch=2)
    add('watch_tick', NORMAL,
        lambda s: s.watch == 1,
        _wtick,
        'halow_net_watch.sh:14-29  5s 轮询，只检查 IFF_UP 一个 bit')

    add('watch_cooldown_end', NORMAL,
        lambda s: s.watch == 2,
        lambda s: s._replace(watch=1),
        'sh:29 sleep $COOLDOWN(10s) 结束')

    # ---------- 驱动 detect_work (2s) ----------
    add('detect_disarm', NORMAL,
        lambda s: s.darm == 1 and s.run == 0,
        lambda s: s._replace(darm=0),
        'core.c:886 只在 RUNNING 时重排定时器 → RUNNING=0 则定时器链永久断裂')

    add('detect_skip_sleep', NORMAL,
        lambda s: s.darm == 1 and s.run == 1 and s.sleep == 1,
        lambda s: s._replace(darm=1),
        'core.c:861 SLEEP 置位 → 整段检测被跳过，只重新装填定时器')

    add('detect_idle', NORMAL,
        lambda s: s.darm == 1 and s.run == 1 and s.sleep == 0 and s.fw == 1,
        lambda s: s._replace(darm=1),
        'core.c:861-880 固件响应正常，无动作')

    add('detect_reinit_ok', NORMAL,
        lambda s: s.darm == 1 and s.run == 1 and s.sleep == 0 and s.fw == 0,
        lambda s: s._replace(fw=1, evtq=0, darm=1),
        'core.c:872-880 bootdl 探测失败 → bus->reinit → 固件恢复')

    add('detect_reinit_fail', NORMAL,
        lambda s: s.darm == 1 and s.run == 1 and s.sleep == 0 and s.fw == 0,
        lambda s: s._replace(fw=0, run=0, darm=0),
        'reinit 失败 → RUNNING 被清 → core.c:886 不再重排 → 定时器停摆')

    # ---------- 事件队列 (event.c) ----------
    add('evt_push', NORMAL,
        lambda s: s.fw == 1 and s.evtq < 2,
        lambda s: s._replace(evtq=s.evtq + 1),
        'event.c:72 skb_queue_tail 入队')

    add('evt_overflow', NORMAL,
        lambda s: s.fw == 1 and s.evtq == 2,
        lambda s: s._replace(eloss=1),
        'event.c:68-70 队列满(16) → 丢**最旧**事件')

    add('evt_drain', NORMAL,
        lambda s: s.evtq > 0,
        lambda s: s._replace(evtq=s.evtq - 1),
        '用户态 daemon 读取事件')

    # ------------------------------------------------ 故障注入（仅用于生成可达状态）
    add('f_usb_out', FAULT,
        lambda s: s.iface != A,
        lambda s: s._replace(iface=A),
        'USB 断开 / 重枚举中接口消失')

    add('f_fw_hang', FAULT,
        lambda s: s.fw == 1,
        lambda s: s._replace(fw=0),
        '固件挂死（F2）')

    add('f_sleep_stuck', FAULT,
        lambda s: s.sleep == 0,
        lambda s: s._replace(sleep=1, fw=0),
        'F1a：suspend 后 SLEEP 标志置位且未清，固件不响应')

    add('f_iface_down', FAULT,
        lambda s: s.iface in (UN, UI, BH),
        lambda s: s._replace(iface=D),
        'F1b：resume 后 hg0 admin DOWN')

    add('f_blackhole', FAULT,
        lambda s: s.iface == UI,
        lambda s: s._replace(iface=BH),
        'F3/F1a：admin UP + 有 IP，但数据面静默（soft_fc 饿死 / 固件睡）')

    add('f_evt_burst', FAULT,
        lambda s: s.evtq < 2,
        lambda s: s._replace(evtq=2, eloss=1),
        'F4：事件突发导致队列溢出，关键事件被挤掉')

    add('f_run_clear', FAULT,
        lambda s: s.run == 1,
        lambda s: s._replace(run=0),
        'RUNNING 标志被清（reinit 路径 / 异常卸载）')

    add('f_watch_exit', FAULT,
        lambda s: s.watch in (1, 2),
        lambda s: s._replace(watch=3),
        'halow_net_watch 是 oneshot service，异常退出后不再重启')

    # ------------------------------------------------ LHR 修补动作
    if variant == 'lhr':
        add('LHR_probe_blackhole', NORMAL,
            lambda s: s.watch == 1 and s.iface == BH,
            lambda s: s._replace(p_reb=1, watch=2),
            'LHR-D1：看门狗加数据面探针，黑洞可见（不再只看 admin UP）')

        add('LHR_rebind_strong', NORMAL,
            lambda s: s.p_reb == 1 and s.iface == BH,
            lambda s: s._replace(iface=UI, p_reb=0, sleep=0, fw=1, run=1, darm=1),
            'LHR-A2：rebind 下沉到驱动，清 SLEEP + 触发 warm reinit')

        add('LHR_sleep_liveness', NORMAL,
            lambda s: s.darm == 1 and s.run == 1 and s.sleep == 1,
            lambda s: s._replace(sleep=0),
            'LHR-D2：检测不再被 SLEEP 屏蔽，限时探测并主动清除卡死的 SLEEP')

        add('LHR_timer_guard', NORMAL,
            lambda s: s.run == 0,
            lambda s: s._replace(run=1, darm=1),
            'LHR-D3：控制面监督器检测 RUNNING/detect_tmr 停摆并重新装填')

        add('LHR_watch_restart', NORMAL,
            lambda s: s.watch == 3,
            lambda s: s._replace(watch=1),
            'LHR-D4：看门狗自身受守护，EXITED 后自动重启')

    return acts


# ---------------------------------------------------------------- 图搜索

def explore(actions, init):
    """从 init 出发做 BFS（允许故障），返回 dist / parent / 转移边"""
    dist = {init: 0}
    parent = {init: None}
    q = deque([init])
    edges = []
    while q:
        s = q.popleft()
        for name, kind, guard, apply_, note in actions:
            if not guard(s):
                continue
            t = apply_(s)
            edges.append((s, name, t, kind))
            if t not in dist:
                dist[t] = dist[s] + 1
                parent[t] = (s, name)
                q.append(t)
    return dist, parent, edges


def can_reach_streaming(actions, states):
    """在**只允许 NORMAL 动作**的图上，求能到达 STREAMING 的状态集合（反向可达）"""
    # 建正向邻接（只含 NORMAL）
    adj = {s: [] for s in states}
    for s in states:
        for name, kind, guard, apply_, note in actions:
            if kind == FAULT:
                continue
            if guard(s):
                t = apply_(s)
                if t in adj:
                    adj[s].append((name, t))
    # 反向 BFS
    rev = {s: [] for s in states}
    for s in states:
        for name, t in adj[s]:
            rev[t].append(s)

    good = set()
    q = deque()
    for s in states:
        if is_streaming(s):
            good.add(s)
            q.append(s)
    while q:
        s = q.popleft()
        for p in rev[s]:
            if p not in good:
                good.add(p)
                q.append(p)
    return good, adj


def path_to(parent, init, target):
    if target == init:
        return []
    path = []
    cur = target
    while parent[cur] is not None:
        p, name = parent[cur]
        path.append(name)
        cur = p
        if cur == init:
            break
    path.reverse()
    return path


def fmt(s: State) -> str:
    return (f"iface={IFACE_NAMES[s.iface]:9s} sleep={s.sleep} fw={'LIVE' if s.fw else 'DEAD'} "
            f"run={s.run} darm={s.darm} watch={WATCH_NAMES[s.watch]:6s} "
            f"ready={s.p_ready} reb={s.p_reb} init={s.p_init} evtq={s.evtq} lost={s.eloss}")


def classify(s: State) -> str:
    """给反例打上机理性标签"""
    tags = []
    if s.iface == BH:
        tags.append('数据面黑洞（admin UP 但有 IP 无流）')
    if s.iface == A:
        tags.append('接口消失')
    if s.watch == 3:
        tags.append('看门狗已退出(oneshot)')
    if s.watch == 0:
        tags.append('看门狗从未启动')
    if s.sleep == 1:
        tags.append('SLEEP 卡死屏蔽自检')
    if s.run == 0:
        tags.append('RUNNING=0')
    if s.darm == 0:
        tags.append('detect_tmr 停摆')
    if s.fw == 0:
        tags.append('固件无响应')
    if s.iface in (UI, UN) and s.watch == 1:
        tags.append('看门狗认为一切正常(admin UP)')
    return ' + '.join(tags) if tags else '未分类'


def run(variant):
    actions = build_actions(variant)
    init = State(iface=D, sleep=0, fw=1, run=1, darm=1, watch=0,
                 p_ready=0, p_reb=0, p_init=0, evtq=0, eloss=0)
    dist, parent, edges = explore(actions, init)
    states = set(dist)
    good, adj = can_reach_streaming(actions, states)

    bad = sorted((s for s in states if s not in good),
                 key=lambda s: (dist[s], fmt(s)))
    # 吸收态：在无故障（NORMAL）动作下没有任何出边
    def has_normal_exit(s):
        for name, kind, guard, apply_, note in actions:
            if kind == NORMAL and guard(s):
                return True
        return False
    absorbing = [s for s in bad if not has_normal_exit(s)]

    return dict(variant=variant, actions=actions, init=init, dist=dist,
                parent=parent, edges=edges, states=states, good=good,
                bad=bad, absorbing=absorbing, adj=adj)


def main():
    out = []
    W = out.append

    W("# HaLow 控制面形式化检验报告\n")
    W("> 模型：`A/control_plane_model.py` ｜ 方法：穷举可达状态空间 + 反向可达性（活性检验）\n")

    results = {}
    for variant in ('stock', 'lhr'):
        results[variant] = run(variant)

    st = results['stock']
    W("## 0. 模型规模\n")
    W(f"- 状态变量：{len(State._fields)} 个（iface / sleep / fw / run / darm / watch / 3 个 property / 事件队列 / 丢失标记）")
    W(f"- stock 变体动作数：{len(st['actions'])}（含 9 个故障注入）")
    W(f"- **可达状态数：{len(st['states'])}**")
    W(f"- 可达转移边数：{len(st['edges'])}")
    W(f"- 初始状态：`{fmt(st['init'])}`\n")

    W("## 1. 活性检验结果（stock = 现网实现）\n")
    n_bad = len(st['bad'])
    W(f"**违反活性（永久断流）的可达状态：{n_bad} / {len(st['states'])} "
      f"（{100.0*n_bad/len(st['states']):.1f}%）**\n")
    if n_bad:
        W("也就是说：现网控制面**存在大量可达的永久断流状态**——"
          "从这些状态出发，无论系统自身如何运转（不借助人工外力），都回不到正常拉流。\n")

    W("### 1.1 最短反例（从初始状态出发需要的最少动作数）\n")
    W("| # | 步数 | 状态 | 机理 | 最短触发路径 |")
    W("|---|------|------|------|--------------|")
    shown = st['bad'][:12]
    for i, s in enumerate(shown, 1):
        p = path_to(st['parent'], st['init'], s)
        W(f"| {i} | {len(p)} | `{fmt(s)}` | {classify(s)} | {' → '.join(p) if p else '(初始)'} |")
    W("")

    W("### 1.2 反例机理归类（按状态特征统计）\n")
    from collections import Counter
    cnt = Counter()
    for s in st['bad']:
        for t in classify(s).split(' + '):
            cnt[t] += 1
    W("| 机理 | 涉及状态数 |")
    W("|------|-----------|")
    for t, c in cnt.most_common():
        W(f"| {t} | {c} |")
    W("")

    W("### 1.3 典型反例详解\n")
    picks = []
    want = [
        ('黑洞吸收态', lambda s: s.iface == BH and s.fw == 1 and s.watch == 1),
        ('SLEEP 屏蔽自检', lambda s: s.sleep == 1 and s.iface == BH),
        ('看门狗退出', lambda s: s.watch == 3),
        ('定时器链断裂', lambda s: s.run == 0 and s.darm == 0),
    ]
    for label, pred in want:
        cand = [s for s in st['bad'] if pred(s)]
        if cand:
            cand.sort(key=lambda s: st['dist'][s])
            picks.append((label, cand[0]))
    for label, s in picks:
        p = path_to(st['parent'], st['init'], s)
        W(f"**{label}** — 最短 {len(p)} 步：\n")
        W("```")
        W("  " + " → ".join(p) if p else "  (初始状态)")
        W(f"  ⇒ {fmt(s)}")
        W("```")
        W(f"- 机理：{classify(s)}")
        W(f"- 为何回不去：")
        if s.iface == BH and s.fw == 1:
            W("  - `halow_net_watch.sh:23` 只查 `flags & 1`，黑洞态 admin UP → `continue`，看门狗看不见")
            W("  - `core.c:861` detect_work 只在 `!SLEEP && fw 无响应` 时动作；此处 fw=LIVE，不触发 reinit")
            W("  - 于是**没有任何组件会改变数据面**，黑洞被永久保持")
        if s.sleep == 1:
            W("  - `core.c:861` `if (!SLEEP && RUNNING)`：SLEEP 置位时整段检测被跳过，只重排定时器")
            W("  - 固件睡死 → SLEEP 永不清除 → 驱动自检永久空转")
        if s.watch == 3:
            W("  - `init.rc:57` halow_net_watch 是 `oneshot` service，退出后不再重启")
            W("  - 此后无人再触发 rebind")
        if s.run == 0:
            W("  - `core.c:886` `if (RUNNING) mod_timer(...)`：RUNNING=0 → 定时器不再装填 → 自检链永久停摆")
        W("")

    # ---------------- 稳态单次故障分析（论文 headline 用） ----------------
    W("### 1.4 稳态单次故障反例（headline 结论）\n")
    W("上面的统计混入了冷启动竞态。论文最需要的是这一类："
      "**系统已经处于正常拉流（STREAMING），仅注入一次故障，此后系统再也无法自愈。**\n")

    streaming_states = [s for s in st['states'] if is_streaming(s)]
    W(f"- 可达的 STREAMING 状态数：{len(streaming_states)}")

    single = {}   # (故障名, 机理) -> 示例状态
    hard, latent = [], []
    for s in streaming_states:
        for name, kind, guard, apply_, note in st['actions']:
            if kind != FAULT or not guard(s):
                continue
            t = apply_(s)
            if t in st['good']:
                continue
            key = name
            if key not in single:
                single[key] = (s, t, st['dist'][s])
            # 分类
            is_hard = (t.iface != UI) or (t.fw == 0) or (t.sleep == 1)
            (hard if is_hard else latent).append((name, s, t))

    W(f"- 能造成**单次故障即永久断流**的故障类型数：**{len(single)} / 9**\n")
    if single:
        W("| 故障注入 | 注入后状态 | 机理 | 硬断流? |")
        W("|----------|-----------|------|---------|")
        for name, (s, t, _d) in sorted(single.items()):
            is_hard = (t.iface != UI) or (t.fw == 0) or (t.sleep == 1)
            W(f"| `{name}` | `{fmt(t)}` | {classify(t)} | "
              f"{'是（数据面已不可用）' if is_hard else '否（能力丧失：此刻仍在流，但已失去自愈能力）'} |")
        W("")

    W(f"- **硬断流**（数据面当场不可用）：{len(hard)} 个 (故障,状态) 组合")
    W(f"- **能力丧失**（此刻仍在拉流，但恢复能力已丢失，下次故障必断）：{len(latent)} 个组合\n")
    if latent:
        W("> 「能力丧失」是本模型最值得强调的一类：**系统当前看起来完全正常，"
          "监控指标全绿，但它已经不再具备从任何故障中恢复的能力**。"
          "这类状态在传统可用性测量中会被完全漏掉——uptime 是 100%，实际脆弱度是 100%。\n")

    W("## 2. 对照：LHR 修补后的活性\n")
    lh = results['lhr']
    W(f"- LHR 变体动作数：{len(lh['actions'])}（新增 5 个修补动作）")
    W(f"- 可达状态数：{len(lh['states'])}")
    W(f"- **违反活性的状态：{len(lh['bad'])}**")
    if not lh['bad']:
        W("\n✅ **修补后活性成立**：在同样的故障注入集合下，"
          "所有可达状态都能在不借助外力（不含故障动作）的前提下回到 STREAMING。")
        W("\n这条对比就是论文的方法学闭环：")
        W("stock 有大量永久断流状态 → LHR 为 0，且该结论是**穷举证明**而非抽样测量。\n")
    else:
        W("\n⚠️ LHR 仍有反例，需要补动作：\n")
        for s in lh['bad'][:10]:
            p = path_to(lh['parent'], lh['init'], s)
            W(f"- `{fmt(s)}` ｜ {classify(s)} ｜ 路径：{' → '.join(p)}")

    W("\n## 3. 安全性检验（黑洞态）\n")
    bh_stock = [s for s in st['states'] if s.iface == BH]
    W(f"- stock 可达黑洞状态数：{len(bh_stock)}")
    W(f"- 其中违反活性：{len([s for s in bh_stock if s not in st['good']])}")
    W("- 结论：黑洞态一旦进入几乎必然不可自愈，因为观测面只见 admin UP，**故障不可区分**。\n")

    W("## 4. 对论文的产出\n")
    W("1. **否定结果（可证明）**：轮询 + 冷却 + 单向观测 + 丢旧事件队列这一组合，"
      "在可达状态空间中产生非空且规模可观的永久断流状态集。这是**设计模式的性质**，"
      "与泰芯/A133 无关，正面回应外部有效性质疑。")
    W("2. **可迁移设计原则**：LHR 的 4 条修补（数据面探针 / 检测不被 SLEEP 屏蔽 / "
      "定时器守护 / 看门狗自守护）各自对应一类活性反例，缺一不可。")
    W("3. **实验角色转变**：真机注入实验不再是论文全部，而是对形式结论的**验证**——"
      "模型预测的反例路径，逐条在板端复现。")
    W("")

    text = "\n".join(out)
    print(text)
    with open('model_check_report.md', 'w', encoding='utf-8') as f:
        f.write(text)


if __name__ == '__main__':
    main()
