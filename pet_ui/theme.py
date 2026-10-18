"""配色与渲染参数常量（原 pet_ui.py 模块级常量）。

集中在这里，供 renderer / popup / table 等子模块共享，
避免各文件重复硬编码同一套色值。
"""

# 用这种不常见颜色做"抠底"透明色
TRANSPARENT = '#ff00ff'
TRANSPARENT_RGB = (255, 0, 255)

# 时尚配色：主色（水母粉）、深色文字、浅色底
PRIMARY = '#ff7aa2'
PRIMARY_DARK = '#ff4d80'
TEXT_DARK = '#2b2b2b'
TEXT_MUTED = '#8a8a8a'

# ---------- 桌宠渲染与动画参数 ----------
IDLE_FRAMES = 10          # 呼吸循环帧数
IDLE_INTERVAL = 220       # 呼吸每帧间隔(ms)，约 2.2s 一个呼吸周期
SQUASH_INTERVAL = 45      # 点击挤压每帧间隔(ms)
PAD_X = 24                # 帧画布左右留白（容纳挤压变宽与呼吸）
PAD_TOP = 8               # 帧画布顶部留白
SHADOW_H_RATIO = 0.16     # 阴影高度占人物高度比例
