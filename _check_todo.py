"""db_todo.py 快速自检脚本（手动运行，非程序一部分）。

用法：python _check_todo.py
会在数据库里插入临时测试数据，验证核心查询逻辑后清理。
若不想改动真实数据，可先注释掉结尾的清理调用再看结果。
"""
import datetime

import db_todo


def _today():
    return datetime.datetime.now().strftime('%Y-%m-%d')


def main():
    print('== db_todo 自检 ==')
    print('当前日期:', _today())

    # 插入测试任务
    tid1 = db_todo.add_todo('测试-今天未完成', f'{_today()} 10:00')
    tid2 = db_todo.add_todo('测试-今天已完成', f'{_today()} 11:00')
    tid3 = db_todo.add_todo('测试-昨天未完成', '2026-10-17 23:00')
    tid4 = db_todo.add_todo('测试-未来', '2026-10-25 09:00')

    # 勾掉今天的 tid2
    db_todo.set_done(tid2, True)

    print('\n== format_due 汉字展示 ==')
    print('  2026-10-19 14:00 ->', db_todo.format_due('2026-10-19 14:00'))

    print('\n== 全部待办（按截止升序，近→远）==')
    for r in db_todo.get_all_todos():
        print('  ', r)

    print('\n== 截止统计（今天/过期/未来）==')
    print('  ', db_todo.get_due_stats())

    print('\n未完成数:', db_todo.get_pending_count())
    print('有紧急(<=12h)任务:', db_todo.has_urgent_pending())

    # 清理
    for tid in (tid1, tid2, tid3, tid4):
        db_todo.delete_todo(tid)
    print('\n== 已清理测试数据 ==')


if __name__ == '__main__':
    main()
