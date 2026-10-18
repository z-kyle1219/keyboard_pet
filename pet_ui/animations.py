"""桌宠动画状态机：呼吸循环、点击挤压回弹、拖拽拎起。

从原 pet_ui.py 原样迁移。作为 Mixin 混入 PetApp，
所有方法仍以 self 访问窗口与帧缓存，行为与拆分前完全一致。
"""
import math

from pet_ui.theme import IDLE_FRAMES, IDLE_INTERVAL, SQUASH_INTERVAL


class AnimationMixin:
    """提供 _idle_pose / _stop_anim / _resume_idle / _animate_idle / _play_squash。"""

    def _idle_pose(self):
        """呼吸循环的姿态序列：[(shadow_scale, lift), ...]。

        吸气时人物上浮、阴影略小；呼气时人物下沉、阴影略大。
        """
        poses = []
        for i in range(IDLE_FRAMES):
            phase = 2 * math.pi * i / IDLE_FRAMES
            lift = round(2.5 * (1 - math.cos(phase)))
            shadow_scale = 0.90 + 0.10 * math.cos(phase)
            poses.append((shadow_scale, lift))
        return poses

    def _stop_anim(self):
        """取消当前排队的动画 tick。"""
        if self._anim_job is not None:
            try:
                self.root.after_cancel(self._anim_job)
            except Exception:
                pass
            self._anim_job = None

    def _resume_idle(self):
        """回到呼吸循环。"""
        self._anim_mode = 'idle'
        self._idle_idx = 0
        self._icon.configure(image=self._idle_photos[0])
        self._animate_idle()

    def _animate_idle(self):
        if self._anim_mode != 'idle':
            return
        self._idle_idx = (self._idle_idx + 1) % len(self._idle_photos)
        self._icon.configure(image=self._idle_photos[self._idle_idx])
        self._anim_job = self.root.after(IDLE_INTERVAL, self._animate_idle)

    def _play_squash(self):
        """点击挤压回弹动画（squash & stretch）。"""
        self._anim_mode = 'squash'
        self._stop_anim()
        idx = [0]

        def step():
            if idx[0] >= len(self._squash_photos):
                self._resume_idle()
                return
            self._icon.configure(image=self._squash_photos[idx[0]])
            idx[0] += 1
            self._anim_job = self.root.after(SQUASH_INTERVAL, step)

        step()
