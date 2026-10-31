#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""离线预览积分台账卡片（不启动桌宠）。

用法（在项目根目录）：
    uv run python scripts/preview_credit_card.py

生成两张图：
    _credit_preview.png        默认态（最高柱标数值）
    _credit_preview_hover.png  悬停态（柱子那一列浮出、显示数值卡片）

先看图确认排版，再打开桌宠，省得来回切窗口。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import credit_stats                        # noqa: E402
from pet_ui.credit_ui import _build_card   # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    data = credit_stats.load_overview(14, force=True)
    print(f"来源: {data['source']}  ok={data['ok']}")
    print(f"今日: {data['today']}  {data['today_credits']:.2f} 积分"
          f" / {data['today_sessions']} 个会话")
    print(f"累计: {data['total_credits']:.2f} 积分"
          f" / 共 {data['total_sessions']} 个会话")
    print(f"本月: {data['month_credits']:.2f} 积分")

    sessions = data.get('day_sessions') or {}
    peak, peak_date = -1.0, None
    for date, credits, has in data['series']:
        flag = '' if has else '  (无记录)'
        cnt = sessions.get(date, 0)
        print(f"  {date}  {credits:8.2f}  {cnt} 会话{flag}")
        if has and credits > peak:
            peak, peak_date = credits, date

    img, _layout = _build_card(data, 1.0)
    out = os.path.join(ROOT, '_credit_preview.png')
    img.save(out)
    print(f'\n默认态: {out}')

    if peak_date:
        idx = [i for i, (d, _c, _h) in enumerate(data['series'])
               if d == peak_date]
        hover = idx[0] if idx else None
        img_hover, _ = _build_card(data, 1.0, hover=hover)
        out_hover = os.path.join(ROOT, '_credit_preview_hover.png')
        img_hover.save(out_hover)
        print(f'悬停态: {out_hover}  ({peak_date}，{peak:.2f} 积分)')


if __name__ == '__main__':
    main()
