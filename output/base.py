"""
音频输出基类
"""
from abc import ABC, abstractmethod
import queue


class BaseOutput(ABC):
    """音频输出抽象基类"""

    @abstractmethod
    def start(self):
        """启动音频输出"""
        pass

    @abstractmethod
    def stop(self):
        """停止音频输出"""
        pass

    @abstractmethod
    def get_queue(self) -> queue.Queue:
        """获取音频队列"""
        pass

    @abstractmethod
    def is_running(self) -> bool:
        """是否正在运行"""
        pass

    @abstractmethod
    def set_volume(self, volume: int):
        """设置音量 (0-100)"""
        pass

    @abstractmethod
    def set_mute(self, muted: bool):
        """设置静音"""
        pass

    def handle_action(self, action_type, **param):
        """执行行为"""
        pass
