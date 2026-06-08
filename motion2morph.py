#!/usr/bin/env python3
"""Motion2Morph — MMDボーン動作を表情モーフ／ボーン揺れキーフレームに変換するツール"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import struct
import math
import os

_BONE_INTERP = bytes([20, 20, 20, 20, 20, 20, 20, 20,
                       107, 107, 107, 107, 107, 107, 107, 107] * 4)


# ══════════════════════════════════════════════════════════════════
#  VMD 読み書き
# ══════════════════════════════════════════════════════════════════

def parse_vmd(filepath):
    bone_frames, morph_frames = [], []
    with open(filepath, 'rb') as f:
        if b'Vocaloid Motion Data' not in f.read(30):
            raise ValueError("VMDファイルではありません")
        f.read(20)
        n = struct.unpack('<I', f.read(4))[0]
        for _ in range(n):
            name  = f.read(15).decode('shift-jis', errors='replace').rstrip('\x00')
            frame = struct.unpack('<I', f.read(4))[0]
            pos   = struct.unpack('<3f', f.read(12))
            rot   = struct.unpack('<4f', f.read(16))
            f.read(64)
            bone_frames.append({'name': name, 'frame': frame, 'pos': pos, 'rot': rot})
        n = struct.unpack('<I', f.read(4))[0]
        for _ in range(n):
            name  = f.read(15).decode('shift-jis', errors='replace').rstrip('\x00')
            frame = struct.unpack('<I', f.read(4))[0]
            value = struct.unpack('<f', f.read(4))[0]
            morph_frames.append({'name': name, 'frame': frame, 'value': value})
    return bone_frames, morph_frames


def write_vmd(filepath, morph_frames=None, bone_out_frames=None, model_name=""):
    morph_frames    = morph_frames    or []
    bone_out_frames = bone_out_frames or []
    with open(filepath, 'wb') as f:
        f.write(b'Vocaloid Motion Data 0002\x00\x00\x00\x00\x00')
        f.write(model_name.encode('shift-jis', errors='replace')[:20].ljust(20, b'\x00'))
        f.write(struct.pack('<I', len(bone_out_frames)))
        for bf in bone_out_frames:
            f.write(bf['name'].encode('shift-jis', errors='replace')[:15].ljust(15, b'\x00'))
            f.write(struct.pack('<I', bf['frame']))
            f.write(struct.pack('<3f', *bf['pos']))
            f.write(struct.pack('<4f', *bf['rot']))
            f.write(_BONE_INTERP)
        f.write(struct.pack('<I', len(morph_frames)))
        for mf in morph_frames:
            f.write(mf['name'].encode('shift-jis', errors='replace')[:15].ljust(15, b'\x00'))
            f.write(struct.pack('<I', mf['frame']))
            f.write(struct.pack('<f', mf['value']))
        f.write(struct.pack('<I', 0) * 4)


# ══════════════════════════════════════════════════════════════════
#  PMX パーサー（ボーン名・モーフ名のみ取得）
# ══════════════════════════════════════════════════════════════════

def parse_pmx(filepath):
    with open(filepath, 'rb') as f:
        if f.read(4) != b'PMX ':
            raise ValueError("PMXファイルではありません")
        f.read(4)
        nc = struct.unpack('<B', f.read(1))[0]
        s = f.read(nc)
        enc, uvc, vis, tis, mis, bis, mois, ris = (
            s[0], s[1], s[2], s[3], s[4], s[5], s[6], s[7])

        def rt():
            n = struct.unpack('<I', f.read(4))[0]
            return f.read(n).decode('utf-16-le' if enc == 0 else 'utf-8', errors='replace')

        rt(); rt(); rt(); rt()

        for _ in range(struct.unpack('<I', f.read(4))[0]):  # 頂点
            f.read(32 + uvc * 16)
            dt = struct.unpack('<B', f.read(1))[0]
            ds = {0: bis, 1: bis*2+4, 2: bis*4+16, 3: bis*2+40, 4: bis*4+16}
            if dt not in ds:
                raise ValueError(f"未知の頂点デフォームタイプ: {dt}")
            f.read(ds[dt]); f.read(4)

        f.read(struct.unpack('<I', f.read(4))[0] * vis)  # 面
        for _ in range(struct.unpack('<I', f.read(4))[0]): rt()  # テクスチャ

        for _ in range(struct.unpack('<I', f.read(4))[0]):  # 材質
            rt(); rt()
            f.read(16 + 12 + 4 + 12 + 1 + 16 + 4)
            f.read(tis * 2); f.read(1)
            f.read(1 if struct.unpack('<B', f.read(1))[0] == 0 else tis)
            rt(); f.read(4)

        bones = []
        for _ in range(struct.unpack('<I', f.read(4))[0]):  # ボーン
            bones.append(rt()); rt()
            f.read(12); f.read(bis); f.read(4)
            fl = struct.unpack('<H', f.read(2))[0]
            f.read(bis if fl & 0x0001 else 12)
            if fl & 0x0300: f.read(bis + 4)
            if fl & 0x0400: f.read(12)
            if fl & 0x0800: f.read(24)
            if fl & 0x2000: f.read(4)
            if fl & 0x0020:
                f.read(bis); f.read(4); f.read(4)
                lc = struct.unpack('<I', f.read(4))[0]
                for _ in range(lc):
                    f.read(bis)
                    if struct.unpack('<B', f.read(1))[0]: f.read(24)

        morphs = []
        for _ in range(struct.unpack('<I', f.read(4))[0]):  # モーフ
            morphs.append(rt()); rt()
            f.read(1)
            mt = struct.unpack('<B', f.read(1))[0]
            oc = struct.unpack('<I', f.read(4))[0]
            ms = {0: mois+4, 1: vis+12, 2: bis+28,
                  3: vis+16, 4: vis+16, 5: vis+16, 6: vis+16, 7: vis+16,
                  8: mis+113, 9: mois+4, 10: ris+25}
            if mt not in ms: raise ValueError(f"未知のモーフタイプ: {mt}")
            for _ in range(oc): f.read(ms[mt])

    return bones, morphs


# ══════════════════════════════════════════════════════════════════
#  数学ヘルパー
# ══════════════════════════════════════════════════════════════════

def _quat_angle(q1, q2):
    return 2.0 * math.acos(min(1.0, abs(sum(a*b for a,b in zip(q1,q2)))))

def _vec3_dist(p1, p2):
    return math.sqrt(sum((a-b)**2 for a,b in zip(p1,p2)))

def _quat_mul(q1, q2):
    x1,y1,z1,w1 = q1; x2,y2,z2,w2 = q2
    return (w1*x2+x1*w2+y1*z2-z1*y2, w1*y2-x1*z2+y1*w2+z1*x2,
            w1*z2+x1*y2-y1*x2+z1*w2, w1*w2-x1*x2-y1*y2-z1*z2)

def _axis_quat(axis, angle):
    s, c = math.sin(angle/2), math.cos(angle/2)
    return {'X':(s,0,0,c), 'Y':(0,s,0,c), 'Z':(0,0,s,c)}[axis]


# ══════════════════════════════════════════════════════════════════
#  強度計算（複数ボーン対応・全フレーム補間）
# ══════════════════════════════════════════════════════════════════

def _bone_raw_intensities(bone_frames, bone_name, use_pos, use_rot, mode):
    """
    1本のボーンの強度リストを返す。
    戻り値: (frame_nums, raw_values)  ※正規化なし
    """
    kfs = sorted((f for f in bone_frames if f['name'] == bone_name),
                 key=lambda x: x['frame'])
    if len(kfs) < 2:
        return [], []

    fnums = [k['frame'] for k in kfs]
    if mode == 'velocity':
        raw = [0.0]
        for i in range(1, len(kfs)):
            prev, cur = kfs[i-1], kfs[i]
            dt = max(1, cur['frame'] - prev['frame'])
            v = 0.0
            if use_pos: v += _vec3_dist(cur['pos'], prev['pos']) / dt
            if use_rot: v += _quat_angle(cur['rot'], prev['rot']) / dt
            raw.append(v)
    else:  # displacement
        ref_pos, ref_rot = kfs[0]['pos'], kfs[0]['rot']
        raw = []
        for kf in kfs:
            v = 0.0
            if use_pos: v += _vec3_dist(kf['pos'], ref_pos)
            if use_rot: v += _quat_angle(kf['rot'], ref_rot)
            raw.append(v)

    return fnums, raw


def _interp_at(fnums, vals, target):
    """キーフレーム列を target フレームで線形補間する。"""
    if not fnums:
        return 0.0
    if target <= fnums[0]:  return vals[0]
    if target >= fnums[-1]: return vals[-1]
    for i in range(len(fnums)-1):
        if fnums[i] <= target <= fnums[i+1]:
            t = (target - fnums[i]) / max(1, fnums[i+1] - fnums[i])
            return vals[i]*(1-t) + vals[i+1]*t
    return 0.0


def calc_combined_dense(bone_frames, drivers, use_pos, use_rot, mode):
    """
    複数のドライバーボーンの強度を全フレームで加重合成する。

    drivers : [(bone_name, weight), ...]
    戻り値  : (all_frames, combined)
               all_frames … 全ドライバー範囲の連続フレームリスト
               combined   … [0,1] 正規化済み合成強度（1フレームずつ）
    """
    series = []
    for bone_name, weight in drivers:
        fnums, raw = _bone_raw_intensities(bone_frames, bone_name, use_pos, use_rot, mode)
        if not fnums:
            continue
        peak = max(raw) or 1.0
        normed = [v / peak for v in raw]
        series.append((fnums, normed, weight))

    if not series:
        return [], []

    f_min = min(fn[0]  for fn, _, _ in series)
    f_max = max(fn[-1] for fn, _, _ in series)
    all_frames = list(range(f_min, f_max + 1))

    total_w = sum(w for _, _, w in series)
    combined = [
        sum(_interp_at(fn, nrm, fr) * w for fn, nrm, w in series) / total_w
        for fr in all_frames
    ]

    peak = max(combined) or 1.0
    combined = [v / peak for v in combined]

    return all_frames, combined


# ══════════════════════════════════════════════════════════════════
#  フィルタリング
# ══════════════════════════════════════════════════════════════════

def _gaussian_smooth(values, window):
    """ガウス加重移動平均（ボックスフィルタより自然な曲線になる）。"""
    if window <= 1 or not values:
        return values[:]
    sigma = max(1.0, window / 3.0)
    half  = window // 2
    kernel = [math.exp(-0.5 * (i / sigma)**2) for i in range(-half, half+1)]
    k_sum  = sum(kernel)
    kernel = [k / k_sum for k in kernel]
    n = len(values)
    result = []
    for i in range(n):
        total = sum(values[max(0, min(n-1, i-half+j))] * kernel[j]
                    for j in range(len(kernel)))
        result.append(total)
    return result


def apply_inertia(values, inertia):
    """慣性（余韻）: EMAフィルタ  Value_t = v*(1-ι) + prev*ι"""
    if inertia <= 0:
        return values[:]
    result = [values[0]]
    for v in values[1:]:
        result.append(v * (1.0 - inertia) + result[-1] * inertia)
    return result


def _reduce_keyframes(frames, values, threshold=0.001, max_interval=4):
    """
    値の変化が小さいフレームを間引く。
    threshold    : 前回保存値からの最小変化量
    max_interval : 変化がなくても最大 N フレームごとに保存（曲線保持）
    """
    if len(frames) <= 2:
        return frames[:], values[:]
    out_f, out_v = [frames[0]], [values[0]]
    last_saved = 0
    for i in range(1, len(frames)-1):
        changed  = abs(values[i] - out_v[-1]) >= threshold
        interval = (frames[i] - frames[last_saved]) >= max_interval
        if changed or interval:
            out_f.append(frames[i])
            out_v.append(values[i])
            last_saved = i
    out_f.append(frames[-1])
    out_v.append(values[-1])
    return out_f, out_v


# ══════════════════════════════════════════════════════════════════
#  モーフ変換
# ══════════════════════════════════════════════════════════════════

def compute_morph_frames(bone_frames, drivers, morph_name,
                          sensitivity, smoothing, max_val, inertia,
                          use_pos, use_rot, mode='velocity'):
    """複数ドライバーボーン → モーフキーフレームを生成する。"""
    all_frames, combined = calc_combined_dense(bone_frames, drivers, use_pos, use_rot, mode)
    if not combined:
        return []

    scaled  = [min(max_val, v * sensitivity) for v in combined]
    smooth  = _gaussian_smooth(scaled, smoothing)
    lagged  = apply_inertia(smooth, inertia)
    final   = [min(max_val, max(0.0, v)) for v in lagged]

    out_frames, out_vals = _reduce_keyframes(all_frames, final)

    out = []
    if out_frames[0] > 0:
        out.append({'name': morph_name, 'frame': 0, 'value': 0.0})
    for fn, v in zip(out_frames, out_vals):
        out.append({'name': morph_name, 'frame': fn, 'value': v})
    if out[-1]['value'] > 0.001:
        out.append({'name': morph_name, 'frame': out_frames[-1]+1, 'value': 0.0})
    return out


# ══════════════════════════════════════════════════════════════════
#  ボーン揺れ（スプリング・ダンパーシミュレーション）
# ══════════════════════════════════════════════════════════════════

def _spring_simulate(drive, stiffness, damping):
    """
    スプリング・ダンパーシミュレーション（全フレーム）。
    drive : 各フレームの外力リスト
    """
    pos, vel, result = 0.0, 0.0, []
    for ext in drive:
        acc  = -stiffness * pos - damping * vel + ext
        vel += acc
        pos += vel
        result.append(pos)
    return result


def compute_bone_sway_frames(bone_frames, drivers, tgt_bone,
                              amplitude, stiffness, damping, smoothing,
                              axes, use_pos, use_rot,
                              mode='velocity', bidirectional=True):
    """
    複数ドライバーボーン → ターゲットボーンの揺れキーフレームを生成する。

    bidirectional=True  : 強度の微分を外力にする → 正負両方向の振り子挙動
    bidirectional=False : 強度をそのまま外力にする → 0からプラス方向のみ
    """
    all_frames, combined = calc_combined_dense(bone_frames, drivers, use_pos, use_rot, mode)
    if not combined:
        return []

    # スムージング後に外力生成
    forces = _gaussian_smooth([v * amplitude for v in combined], smoothing)

    if bidirectional and len(forces) > 1:
        # 強度変化量（微分）を外力として使う → 増加で正、減少で負
        raw_d = [0.0] + [forces[i] - forces[i-1] for i in range(1, len(forces))]
        max_d = max(abs(d) for d in raw_d) or 1.0
        max_f = max(abs(f) for f in forces) or 1.0
        drive = [d * (max_f / max_d) for d in raw_d]
    else:
        drive = forces

    sway = {ax: _spring_simulate(drive, stiffness, damping) for ax in axes}

    # キーフレーム間引き（最大変位量で判断）
    max_disp = [max(abs(sway[ax][i]) for ax in axes) for i in range(len(all_frames))]
    out_frames_idx, prev_val = [0], max_disp[0]
    for i in range(1, len(all_frames)-1):
        changed  = abs(max_disp[i] - prev_val) >= 0.0005
        interval = (all_frames[i] - all_frames[out_frames_idx[-1]]) >= 3
        if changed or interval:
            out_frames_idx.append(i)
            prev_val = max_disp[i]
    out_frames_idx.append(len(all_frames)-1)

    out = []
    if all_frames[0] > 0:
        out.append({'name': tgt_bone, 'frame': 0,
                    'pos': (0.0,0.0,0.0), 'rot': (0.0,0.0,0.0,1.0)})

    for idx in out_frames_idx:
        rot = (0.0, 0.0, 0.0, 1.0)
        for ax in axes:
            rot = _quat_mul(rot, _axis_quat(ax, sway[ax][idx]))
        out.append({'name': tgt_bone, 'frame': all_frames[idx],
                    'pos': (0.0,0.0,0.0), 'rot': rot})

    if any(abs(out[-1]['rot'][k]) > 0.001 for k in range(3)):
        out.append({'name': tgt_bone, 'frame': all_frames[-1]+1,
                    'pos': (0.0,0.0,0.0), 'rot': (0.0,0.0,0.0,1.0)})
    return out


# ══════════════════════════════════════════════════════════════════
#  GUI – 複数ボーンリストウィジェット
# ══════════════════════════════════════════════════════════════════

class BoneListWidget(ttk.LabelFrame):
    """
    複数ドライバーボーン＋重みを管理するUIウィジェット。
    各ボーンの「寄与率（重み）」を設定でき、全ボーンの動きを加重合成する。
    """

    def __init__(self, parent, label="ドライバーボーン（複数可）", **kwargs):
        super().__init__(parent, text=label, **kwargs)
        self._drivers: list = []   # [(bone_name, weight), ...]
        self._build()

    def _build(self):
        # ── 左: 現在のリスト ──
        lf = ttk.Frame(self)
        lf.pack(side='left', fill='both', expand=True, padx=4, pady=4)

        self.listbox = tk.Listbox(lf, height=4, selectmode='single',
                                   font=('Arial', 9))
        sb = ttk.Scrollbar(lf, orient='vertical', command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=sb.set)
        self.listbox.pack(side='left', fill='both', expand=True)
        sb.pack(side='left', fill='y')

        # ── 右: 操作パネル ──
        rf = ttk.Frame(self)
        rf.pack(side='left', fill='y', padx=(0,4), pady=4)

        ttk.Label(rf, text="追加するボーン:").pack(anchor='w')
        self.add_combo = ttk.Combobox(rf, state='readonly', width=22)
        self.add_combo.pack(fill='x', pady=(0,4))

        wf = ttk.Frame(rf)
        wf.pack(fill='x', pady=(0,4))
        ttk.Label(wf, text="重み:").pack(side='left')
        self.weight_var = tk.StringVar(value="1.0")
        ttk.Entry(wf, textvariable=self.weight_var, width=5).pack(side='left', padx=4)

        bf = ttk.Frame(rf)
        bf.pack(fill='x')
        ttk.Button(bf, text="＋ 追加", command=self._add,  width=8).pack(side='left')
        ttk.Button(bf, text="× 削除", command=self._remove, width=8).pack(side='left', padx=2)

    def _add(self):
        bone = self.add_combo.get()
        if not bone:
            return
        try:
            w = float(self.weight_var.get())
        except ValueError:
            w = 1.0
        w = max(0.1, min(5.0, w))
        self._drivers.append((bone, w))
        self.listbox.insert('end', f"  {bone:<28} ×{w:.1f}")

    def _remove(self):
        sel = self.listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        self._drivers.pop(idx)
        self.listbox.delete(idx)

    def set_bones(self, names):
        self.add_combo['values'] = names
        if names and not self.add_combo.get():
            self.add_combo.set(names[0])

    def get_drivers(self):
        return list(self._drivers)

    def has_drivers(self):
        return bool(self._drivers)


# ══════════════════════════════════════════════════════════════════
#  GUI – メインアプリ
# ══════════════════════════════════════════════════════════════════

class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Motion2Morph")
        self.root.minsize(700, 650)
        self.bone_frames: list = []

        # 共有状態
        self._vmd_path = tk.StringVar(value="未選択")
        self._pmx_path = tk.StringVar(value="未選択")

        # モーフ変換タブ
        self.morph_var   = tk.StringVar()
        self.m_use_pos   = tk.BooleanVar(value=True)
        self.m_use_rot   = tk.BooleanVar(value=True)
        self.m_mode      = tk.StringVar(value='velocity')
        self.sensitivity = tk.DoubleVar(value=1.0)
        self.smoothing   = tk.IntVar(value=5)
        self.max_val     = tk.DoubleVar(value=1.0)
        self.inertia     = tk.DoubleVar(value=0.7)
        self.generated_morph: list = []

        # ボーン揺れタブ
        self.sway_tgt_var   = tk.StringVar()
        self.s_use_pos      = tk.BooleanVar(value=True)
        self.s_use_rot      = tk.BooleanVar(value=True)
        self.s_mode         = tk.StringVar(value='velocity')
        self.sway_axis_x    = tk.BooleanVar(value=False)
        self.sway_axis_y    = tk.BooleanVar(value=False)
        self.sway_axis_z    = tk.BooleanVar(value=True)
        self.sway_bidir     = tk.BooleanVar(value=True)
        self.sway_amplitude = tk.DoubleVar(value=0.15)
        self.sway_stiffness = tk.DoubleVar(value=0.10)
        self.sway_damping   = tk.DoubleVar(value=0.20)
        self.sway_smoothing = tk.IntVar(value=5)
        self.generated_sway: list = []

        self._build_ui()

    # ── UI 構築 ─────────────────────────────────────────────────

    def _build_ui(self):
        P = dict(padx=6, pady=3)

        # ファイル選択
        ff = ttk.LabelFrame(self.root, text="ファイル選択")
        ff.pack(fill='x', padx=8, pady=4)
        ttk.Button(ff, text="VMD 読み込み", command=self._load_vmd, width=14
                   ).grid(row=0, column=0, **P)
        ttk.Label(ff, textvariable=self._vmd_path, anchor='w'
                  ).grid(row=0, column=1, sticky='ew', **P)
        ttk.Button(ff, text="PMX 読み込み", command=self._load_pmx, width=14
                   ).grid(row=1, column=0, **P)
        ttk.Label(ff, textvariable=self._pmx_path, anchor='w'
                  ).grid(row=1, column=1, sticky='ew', **P)
        ff.columnconfigure(1, weight=1)

        nb = ttk.Notebook(self.root)
        nb.pack(fill='both', expand=True, padx=8, pady=4)
        t1, t2 = ttk.Frame(nb), ttk.Frame(nb)
        nb.add(t1, text="  モーフ変換  ")
        nb.add(t2, text="  ボーン揺れ  ")
        self._build_morph_tab(t1)
        self._build_sway_tab(t2)

        bf = ttk.Frame(self.root)
        bf.pack(fill='x', padx=8, pady=(0,6))
        self.status = tk.StringVar(value="準備完了")
        ttk.Label(bf, textvariable=self.status, foreground='gray').pack(side='left', padx=6)

    # ── モーフ変換タブ ──────────────────────────────────────────

    def _build_morph_tab(self, parent):
        P = dict(padx=6, pady=2)

        # ドライバーボーンリスト
        self.morph_driver_list = BoneListWidget(parent, label="ドライバーボーン（複数可・重み設定対応）")
        self.morph_driver_list.pack(fill='x', padx=6, pady=4)

        sf = ttk.LabelFrame(parent, text="設定")
        sf.pack(fill='x', padx=6, pady=2)

        ttk.Label(sf, text="表情モーフ:").grid(row=0, column=0, sticky='w', **P)
        self.morph_combo = ttk.Combobox(sf, textvariable=self.morph_var,
                                         state='readonly', width=28)
        self.morph_combo.grid(row=0, column=1, sticky='w', **P)

        ttk.Label(sf, text="動きの種類:").grid(row=1, column=0, sticky='w', **P)
        chk = ttk.Frame(sf); chk.grid(row=1, column=1, sticky='w', **P)
        ttk.Checkbutton(chk, text="位置", variable=self.m_use_pos).pack(side='left', padx=4)
        ttk.Checkbutton(chk, text="回転", variable=self.m_use_rot).pack(side='left', padx=4)

        ttk.Label(sf, text="算出モード:").grid(row=2, column=0, sticky='w', **P)
        mf = ttk.Frame(sf); mf.grid(row=2, column=1, sticky='w', **P)
        ttk.Radiobutton(mf, text="速度（激しさ）",
                        variable=self.m_mode, value='velocity').pack(side='left', padx=4)
        ttk.Radiobutton(mf, text="変位（ズレ）",
                        variable=self.m_mode, value='displacement').pack(side='left', padx=4)

        self._slider(sf, 3, "感度 (倍率):",           self.sensitivity,  0.1, 5.0,  "{:.2f}")
        self._slider(sf, 4, "スムージング (フレーム):", self.smoothing,    1,   60,   "{:.0f}", is_int=True)
        self._slider(sf, 5, "最大値:",                 self.max_val,      0.1, 2.0,  "{:.2f}")
        self._slider(sf, 6, "慣性 / 余韻:",            self.inertia,      0.0, 0.99, "{:.2f}")
        ttk.Label(sf, text="慣性↑ → じわっと変化してゆっくり戻る",
                  foreground='gray').grid(row=7, column=0, columnspan=2, sticky='w', padx=6)

        pf = ttk.LabelFrame(parent, text="プレビュー")
        pf.pack(fill='both', expand=True, padx=6, pady=4)
        br = ttk.Frame(pf); br.pack(fill='x', padx=4, pady=2)
        ttk.Button(br, text="▶ プレビュー生成", command=self._morph_preview).pack(side='left', padx=4)
        ttk.Button(br, text="VMD エクスポート", command=self._morph_export).pack(side='left', padx=4)
        self.morph_canvas = tk.Canvas(pf, height=110, bg='#0d1117', relief='sunken', bd=1)
        self.morph_canvas.pack(fill='both', expand=True, padx=6, pady=(0,6))
        self.morph_canvas.bind('<Configure>', lambda _: self._draw_morph())

    # ── ボーン揺れタブ ──────────────────────────────────────────

    def _build_sway_tab(self, parent):
        P = dict(padx=6, pady=2)

        # ドライバーボーンリスト
        self.sway_driver_list = BoneListWidget(parent, label="ドライバーボーン（複数可・重み設定対応）")
        self.sway_driver_list.pack(fill='x', padx=6, pady=4)

        sf = ttk.LabelFrame(parent, text="設定")
        sf.pack(fill='x', padx=6, pady=2)

        ttk.Label(sf, text="ターゲットボーン:").grid(row=0, column=0, sticky='w', **P)
        self.sway_tgt_combo = ttk.Combobox(sf, textvariable=self.sway_tgt_var,
                                            state='readonly', width=28)
        self.sway_tgt_combo.grid(row=0, column=1, sticky='w', **P)

        ttk.Label(sf, text="動きの種類:").grid(row=1, column=0, sticky='w', **P)
        mk = ttk.Frame(sf); mk.grid(row=1, column=1, sticky='w', **P)
        ttk.Checkbutton(mk, text="位置", variable=self.s_use_pos).pack(side='left', padx=4)
        ttk.Checkbutton(mk, text="回転", variable=self.s_use_rot).pack(side='left', padx=4)

        ttk.Label(sf, text="算出モード:").grid(row=2, column=0, sticky='w', **P)
        mf2 = ttk.Frame(sf); mf2.grid(row=2, column=1, sticky='w', **P)
        ttk.Radiobutton(mf2, text="速度（激しさ）",
                        variable=self.s_mode, value='velocity').pack(side='left', padx=4)
        ttk.Radiobutton(mf2, text="変位（ズレ）",
                        variable=self.s_mode, value='displacement').pack(side='left', padx=4)

        ttk.Label(sf, text="揺れ軸:").grid(row=3, column=0, sticky='w', **P)
        ax = ttk.Frame(sf); ax.grid(row=3, column=1, sticky='w', **P)
        ttk.Checkbutton(ax, text="X (前後)", variable=self.sway_axis_x).pack(side='left', padx=4)
        ttk.Checkbutton(ax, text="Y (左右)", variable=self.sway_axis_y).pack(side='left', padx=4)
        ttk.Checkbutton(ax, text="Z (傾き)", variable=self.sway_axis_z).pack(side='left', padx=4)

        ttk.Label(sf, text="揺れ方向:").grid(row=4, column=0, sticky='w', **P)
        df = ttk.Frame(sf); df.grid(row=4, column=1, sticky='w', **P)
        ttk.Checkbutton(df, text="双方向（＋と－の両方に揺れる）",
                        variable=self.sway_bidir).pack(side='left', padx=4)

        self._slider(sf, 5,  "振幅 (rad):",            self.sway_amplitude, 0.01, 1.0,  "{:.3f}")
        self._slider(sf, 6,  "バネ強度 (stiffness):",  self.sway_stiffness, 0.01, 0.50, "{:.3f}")
        self._slider(sf, 7,  "減衰 (damping):",        self.sway_damping,   0.01, 0.99, "{:.3f}")
        self._slider(sf, 8,  "スムージング (フレーム):", self.sway_smoothing, 1,    30,   "{:.0f}", is_int=True)
        ttk.Label(sf, text="バネ強度↓→よく揺れる  減衰↓→長く揺れる  双方向→振り子",
                  foreground='gray').grid(row=9, column=0, columnspan=2, sticky='w', padx=6, pady=2)

        pf = ttk.LabelFrame(parent, text="プレビュー (回転角度 [deg])")
        pf.pack(fill='both', expand=True, padx=6, pady=4)
        br = ttk.Frame(pf); br.pack(fill='x', padx=4, pady=2)
        ttk.Button(br, text="▶ プレビュー生成", command=self._sway_preview).pack(side='left', padx=4)
        ttk.Button(br, text="VMD エクスポート", command=self._sway_export).pack(side='left', padx=4)
        self.sway_canvas = tk.Canvas(pf, height=110, bg='#0d1117', relief='sunken', bd=1)
        self.sway_canvas.pack(fill='both', expand=True, padx=6, pady=(0,6))
        self.sway_canvas.bind('<Configure>', lambda _: self._draw_sway())

    # ── スライダー共通 ──────────────────────────────────────────

    def _slider(self, parent, row, label, var, lo, hi, fmt, is_int=False):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky='w', padx=6, pady=2)
        frame = ttk.Frame(parent)
        frame.grid(row=row, column=1, sticky='w', padx=6, pady=2)
        disp = ttk.Label(frame, text=fmt.format(var.get()), width=7)

        def on_change(v):
            val = int(float(v)) if is_int else float(v)
            if is_int: var.set(val)
            disp.config(text=fmt.format(val))

        ttk.Scale(frame, from_=lo, to=hi, variable=var,
                  orient='horizontal', length=200, command=on_change).pack(side='left')
        disp.pack(side='left', padx=4)

    # ── ファイル読み込み ────────────────────────────────────────

    def _load_vmd(self):
        path = filedialog.askopenfilename(
            title="VMDファイルを選択",
            filetypes=[("VMD files","*.vmd"),("All files","*.*")])
        if not path: return
        try:
            self.bone_frames, _ = parse_vmd(path)
            self._vmd_path.set(os.path.basename(path))
            names = sorted({f['name'] for f in self.bone_frames})
            self._update_bone_combos(names, pmx=False)
            self.status.set(
                f"VMD読み込み完了 — ボーン種 {len(names)} / フレーム {len(self.bone_frames)} 件")
        except Exception as e:
            messagebox.showerror("VMD読み込みエラー", str(e))

    def _load_pmx(self):
        path = filedialog.askopenfilename(
            title="PMXファイルを選択",
            filetypes=[("PMX files","*.pmx"),("All files","*.*")])
        if not path: return
        try:
            bones, morphs = parse_pmx(path)
            self._pmx_path.set(os.path.basename(path))
            self._update_bone_combos(bones, pmx=True)
            self.morph_combo['values'] = morphs
            if morphs: self.morph_var.set(morphs[0])
            self.status.set(
                f"PMX読み込み完了 — ボーン {len(bones)} 個 / モーフ {len(morphs)} 個")
        except Exception as e:
            messagebox.showerror("PMX読み込みエラー", str(e))

    def _update_bone_combos(self, names, pmx: bool):
        self.morph_driver_list.set_bones(names)
        self.sway_driver_list.set_bones(names)
        if pmx:
            self.sway_tgt_combo['values'] = names
            if not self.sway_tgt_var.get() and names:
                self.sway_tgt_var.set(names[0])

    # ── モーフ変換アクション ────────────────────────────────────

    def _morph_preview(self):
        if not self.bone_frames:
            messagebox.showwarning("警告", "VMDファイルを先に読み込んでください。"); return
        if not self.morph_driver_list.has_drivers():
            messagebox.showwarning("警告", "ドライバーボーンを少なくとも1つ追加してください。"); return
        if not self.morph_var.get():
            messagebox.showwarning("警告", "表情モーフを選択してください。"); return
        if not self.m_use_pos.get() and not self.m_use_rot.get():
            messagebox.showwarning("警告", "「位置」または「回転」を選択してください。"); return
        try:
            self.generated_morph = compute_morph_frames(
                self.bone_frames,
                drivers=self.morph_driver_list.get_drivers(),
                morph_name=self.morph_var.get(),
                sensitivity=self.sensitivity.get(),
                smoothing=int(self.smoothing.get()),
                max_val=self.max_val.get(),
                inertia=self.inertia.get(),
                use_pos=self.m_use_pos.get(),
                use_rot=self.m_use_rot.get(),
                mode=self.m_mode.get(),
            )
            self._draw_morph()
            self.status.set(f"モーフ生成完了 — {len(self.generated_morph)} キーフレーム")
        except Exception as e:
            messagebox.showerror("生成エラー", str(e))

    def _morph_export(self):
        if not self.generated_morph:
            messagebox.showwarning("警告", "先にプレビューを生成してください。"); return
        path = filedialog.asksaveasfilename(
            title="VMDファイルに保存（モーフ）", defaultextension=".vmd",
            filetypes=[("VMD files","*.vmd"),("All files","*.*")])
        if not path: return
        try:
            write_vmd(path, morph_frames=self.generated_morph,
                      model_name=self.morph_var.get())
            self.status.set(f"モーフ VMD エクスポート完了 → {os.path.basename(path)}")
            messagebox.showinfo("完了", f"VMDファイルを出力しました:\n{path}")
        except Exception as e:
            messagebox.showerror("エクスポートエラー", str(e))

    # ── ボーン揺れアクション ────────────────────────────────────

    def _sway_preview(self):
        if not self.bone_frames:
            messagebox.showwarning("警告", "VMDファイルを先に読み込んでください。"); return
        if not self.sway_driver_list.has_drivers():
            messagebox.showwarning("警告", "ドライバーボーンを少なくとも1つ追加してください。"); return
        if not self.sway_tgt_var.get():
            messagebox.showwarning("警告", "ターゲットボーンを選択してください。"); return
        axes = [a for a in
                [('X' if self.sway_axis_x.get() else None),
                 ('Y' if self.sway_axis_y.get() else None),
                 ('Z' if self.sway_axis_z.get() else None)] if a]
        if not axes:
            messagebox.showwarning("警告", "揺れ軸を最低ひとつ選択してください。"); return
        if not self.s_use_pos.get() and not self.s_use_rot.get():
            messagebox.showwarning("警告", "「位置」または「回転」を選択してください。"); return
        try:
            self.generated_sway = compute_bone_sway_frames(
                self.bone_frames,
                drivers=self.sway_driver_list.get_drivers(),
                tgt_bone=self.sway_tgt_var.get(),
                amplitude=self.sway_amplitude.get(),
                stiffness=self.sway_stiffness.get(),
                damping=self.sway_damping.get(),
                smoothing=int(self.sway_smoothing.get()),
                axes=axes,
                use_pos=self.s_use_pos.get(),
                use_rot=self.s_use_rot.get(),
                mode=self.s_mode.get(),
                bidirectional=self.sway_bidir.get(),
            )
            self._draw_sway()
            self.status.set(f"ボーン揺れ生成完了 — {len(self.generated_sway)} キーフレーム")
        except Exception as e:
            messagebox.showerror("生成エラー", str(e))

    def _sway_export(self):
        if not self.generated_sway:
            messagebox.showwarning("警告", "先にプレビューを生成してください。"); return
        path = filedialog.asksaveasfilename(
            title="VMDファイルに保存（ボーン揺れ）", defaultextension=".vmd",
            filetypes=[("VMD files","*.vmd"),("All files","*.*")])
        if not path: return
        try:
            write_vmd(path, bone_out_frames=self.generated_sway,
                      model_name=self.sway_tgt_var.get())
            self.status.set(f"ボーン揺れ VMD エクスポート完了 → {os.path.basename(path)}")
            messagebox.showinfo("完了", f"VMDファイルを出力しました:\n{path}")
        except Exception as e:
            messagebox.showerror("エクスポートエラー", str(e))

    # ── グラフ描画 ──────────────────────────────────────────────

    def _draw_morph(self):
        c = self.morph_canvas
        c.delete('all')
        w, h = c.winfo_width(), c.winfo_height()
        if w < 20 or h < 20: return
        if not self.generated_morph:
            c.create_text(w//2, h//2, text="プレビューなし", fill='#484f58', font=('Arial',10))
            return
        PAD = 30
        frames = [mf['frame'] for mf in self.generated_morph]
        vals   = [mf['value'] for mf in self.generated_morph]
        f0, f1 = frames[0], frames[-1]
        v_max  = max(vals) if max(vals) > 0 else 1.0

        def fx(fr): return PAD + (fr-f0)/max(f1-f0,1)*(w-2*PAD)
        def fy(v):  return h - PAD - v/v_max*(h-2*PAD)

        for lv in [0.25,0.5,0.75,1.0]:
            y = fy(lv*v_max)
            c.create_line(PAD,y,w-PAD,y, fill='#21262d', dash=(3,5))
            c.create_text(PAD-4,y, text=f"{lv*v_max:.2f}", fill='#484f58',
                          anchor='e', font=('Arial',7))
        pts = []
        for fr, v in zip(frames, vals): pts += [fx(fr), fy(v)]
        if len(pts) >= 4:
            c.create_line(*pts, fill='#58a6ff', width=1.5, smooth=True)
        c.create_text(PAD,h-4,   text=str(f0), fill='#484f58', anchor='sw', font=('Arial',8))
        c.create_text(w-PAD,h-4, text=str(f1), fill='#484f58', anchor='se', font=('Arial',8))

    def _draw_sway(self):
        """回転角度の折れ線グラフ（0°ラインを中心に上下に振れる）"""
        c = self.sway_canvas
        c.delete('all')
        w, h = c.winfo_width(), c.winfo_height()
        if w < 20 or h < 20: return
        if not self.generated_sway:
            c.create_text(w//2, h//2, text="プレビューなし", fill='#484f58', font=('Arial',10))
            return
        PAD = 34
        frames = [bf['frame'] for bf in self.generated_sway]
        degs   = []
        for bf in self.generated_sway:
            rx, ry, rz, _ = bf['rot']
            mag   = math.sqrt(rx**2 + ry**2 + rz**2)
            angle = math.degrees(2*math.asin(min(1.0,mag))) if mag > 1e-6 else 0.0
            # 最大成分の軸で符号を決定
            dom = max(abs(rx), abs(ry), abs(rz))
            if dom > 1e-6:
                sign_v = rz if abs(rz)==dom else (ry if abs(ry)==dom else rx)
                angle *= math.copysign(1, sign_v)
            degs.append(angle)

        f0, f1   = frames[0], frames[-1]
        v_range  = max(abs(d) for d in degs) if degs else 1.0
        v_range  = v_range if v_range > 0 else 1.0
        cy       = h / 2

        def fx(fr):  return PAD + (fr-f0)/max(f1-f0,1)*(w-2*PAD)
        def fy(deg): return cy - deg/v_range*(cy-PAD)

        c.create_line(PAD,cy,w-PAD,cy, fill='#3a3a5c', dash=(4,3))
        c.create_text(PAD-4,cy, text="0°", fill='#484f58', anchor='e', font=('Arial',7))
        for sign in (1,-1):
            y = fy(sign*v_range)
            c.create_line(PAD,y,w-PAD,y, fill='#21262d', dash=(3,5))
            c.create_text(PAD-4,y, text=f"{sign*v_range:.1f}°",
                          fill='#484f58', anchor='e', font=('Arial',7))
        pts = []
        for fr, dg in zip(frames, degs): pts += [fx(fr), fy(dg)]
        if len(pts) >= 4:
            c.create_line(*pts, fill='#f0a040', width=1.5, smooth=True)
        c.create_text(PAD,h-4,   text=str(f0), fill='#484f58', anchor='sw', font=('Arial',8))
        c.create_text(w-PAD,h-4, text=str(f1), fill='#484f58', anchor='se', font=('Arial',8))


# ══════════════════════════════════════════════════════════════════
if __name__ == '__main__':
    root = tk.Tk()
    App(root)
    root.mainloop()
