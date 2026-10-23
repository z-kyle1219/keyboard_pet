"""配色与渲染参数常量（原 pet_ui.py 模块级常量）。

集中在这里，供 renderer / popup / table / schedule 等子模块共享，
避免各文件重复硬编码同一套色值。

两套日程表主题（改 UI_THEME 一行即可整体切换）：
- 'neon'  深空底 + 霓虹描边（炫光科技）
- 'fresh' 白底 + 马卡龙色（清新明亮）

其余模块（气泡 / 热力图 / 历史表）仍沿用 PRIMARY 粉色体系，
不受日程表主题影响。
"""

# 用这种不常见颜色做"抠底"透明色
TRANSPARENT = '#ff00ff'
TRANSPARENT_RGB = (255, 0, 255)

# 时尚配色：主色（水母粉）、深色文字、浅色底
PRIMARY = '#ff7aa2'
PRIMARY_DARK = '#ff4d80'
TEXT_DARK = '#2b2b2b'
TEXT_MUTED = '#8a8a8a'

# ============================================================
# 日程表主题
# ============================================================
UI_THEME = 'neon'

# ---------- 炫光科技（深空底 + 霓虹）----------
NEON_BG = '#0d1420'          # 窗口底
NEON_CARD = '#131b2a'        # 列表行底
NEON_CARD_HOVER = '#192334'  # 行悬停底
NEON_BORDER = '#1e2a3d'      # 分隔线 / 轨道
NEON_TEXT = '#dbeafe'        # 主文字
NEON_MUTED = '#7c8ba3'       # 次要文字
NEON_FAINT = '#4a5a72'       # 极淡（已完成）
NEON_INK = '#06121a'         # 亮色底上的深色文字/对勾

NEON_RED = '#ff4d6d'         # 已过期
NEON_CYAN = '#22d3ee'        # 今天 / 主强调
NEON_CYAN_DEEP = '#0e93a8'   # 主强调按下态
NEON_LIME = '#a3e635'        # 近期
NEON_VIOLET = '#a78bfa'      # 远期

# 进度条渐变端点（青 → 紫）
NEON_BAR_FROM = (34, 211, 238)
NEON_BAR_TO = (167, 139, 250)

# ---------- 清新明亮（浅底 + 马卡龙）----------
FRESH_BG = '#ffffff'
FRESH_CARD = '#ffffff'
FRESH_CARD_HOVER = '#fbfcfe'
FRESH_BORDER = '#e5e7eb'
FRESH_TEXT = '#2b2b2b'
FRESH_MUTED = '#8a8a8a'
FRESH_FAINT = '#b8bcc4'
FRESH_INK = '#ffffff'

FRESH_RED = '#ef6351'
FRESH_CYAN = '#4895ef'
FRESH_LIME = '#06d6a0'
FRESH_VIOLET = '#9b5de5'
FRESH_BAR_FROM = (72, 149, 239)
FRESH_BAR_TO = (155, 93, 229)


def _pick(name):
    """按 UI_THEME 取色：neon 优先，否则退回 fresh。"""
    neon = globals().get('NEON_' + name)
    fresh = globals().get('FRESH_' + name)
    return neon if (UI_THEME == 'neon' and neon) else (fresh or neon)


# 对外统一入口（schedule.py / checkbox.py 只依赖这些名字）
UI_BG = _pick('BG')
UI_CARD = _pick('CARD')
UI_CARD_HOVER = _pick('CARD_HOVER')
UI_BORDER = _pick('BORDER')
UI_TEXT = _pick('TEXT')
UI_MUTED = _pick('MUTED')
UI_FAINT = _pick('FAINT')
UI_INK = _pick('INK')
UI_ACCENT = _pick('CYAN')

ACC_OVERDUE = _pick('RED')
ACC_TODAY = _pick('CYAN')
ACC_SOON = _pick('LIME')
ACC_FUTURE = _pick('VIOLET')
BAR_FROM = _pick('BAR_FROM')
BAR_TO = _pick('BAR_TO')

# 勾选框尺寸（用户反馈原生框太小）
CHECKBOX_SIZE = 26


def tint(color, base, ratio=0.18):
    """把 color 按 ratio 混入 base，得到低饱和的"半透明霓虹"底色。

    tkinter 控件不支持透明度，因此用混色模拟霓虹色块底：
    深色主题下得到"暗底透彩"，浅色主题下得到"极浅彩底"。
    """
    try:
        c = color.lstrip('#')
        b = base.lstrip('#')
        cr, cg, cb = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
        br, bg, bb = int(b[0:2], 16), int(b[2:4], 16), int(b[4:6], 16)
        return '#%02x%02x%02x' % (
            int(br + (cr - br) * ratio),
            int(bg + (cg - bg) * ratio),
            int(bb + (cb - bb) * ratio),
        )
    except Exception:
        return base


# ============================================================
# 气泡主题（鎏金国潮 gold）
# ============================================================
BUBBLE_BG = '#161009'          # 玄黑底
BUBBLE_BORDER = '#6b5220'      # 描金外框
BUBBLE_INNER = '#2a1f0c'       # 内层细线
BUBBLE_GOLD = '#e8b64c'        # 主金
BUBBLE_GOLD_LIGHT = '#f0d68a'  # 亮金（渐变亮端 / 揭示徽章文字）
BUBBLE_GOLD_DARK = '#3a2600'   # 金底上的深字
BUBBLE_EDGE = '#b98a2e'        # 金块描边
BUBBLE_RED = '#c0392b'         # 昨日冠军（朱红）
BUBBLE_TEXT = '#e8dcc0'        # 正文

# ============================================================
# 关机提醒气泡主题（渐变粉卡，粉→浅紫柔和过渡）
# ============================================================
TIP_BG = '#ffd6e4'            # 底色回退值（渐变画失败时用）
TIP_GRAD_FROM = '#ffd6e4'     # 渐变起点（左上，柔粉）
TIP_GRAD_TO = '#e8d5f5'       # 渐变终点（右下，浅紫）
TIP_TEXT = '#7a2e5c'          # 正文深紫红
TIP_BTN = '#ffffff'           # 按钮白底
TIP_BTN_HOVER = '#ffeef4'     # 按钮悬停（极浅粉）
TIP_BTN_TEXT = '#c2366b'      # 按钮文字深粉
TIP_RADIUS = 18               # 大圆角

# ---------- 桌宠渲染与动画参数 ----------
IDLE_FRAMES = 10          # 呼吸循环帧数
IDLE_INTERVAL = 220       # 呼吸每帧间隔(ms)，约 2.2s 一个呼吸周期
SQUASH_INTERVAL = 45      # 点击挤压每帧间隔(ms)
PAD_X = 24                # 帧画布左右留白（容纳挤压变宽与呼吸）
PAD_TOP = 8               # 帧画布顶部留白
SHADOW_H_RATIO = 0.16     # 阴影高度占人物高度比例
