# version.py
"""
集中管理应用版本号与元信息。
只需要改 __version__ 即可在整个项目生效。
支持附加构建号/提交号（可通过环境变量注入）。
"""

__app_name__ = "Upgrade_Tool"
__version__ = "1.8"   # ← 以后只改这里
__author__ = "Wayne"
__homepage__ = ""       # 可留空或填项目地址

# 可选：CI/本地环境注入的构建信息（没有也不影响）
import os
__build__  = os.environ.get("APP_BUILD", "").strip()          # 形如 "45"
__commit__ = os.environ.get("GIT_COMMIT", "").strip()         # 形如 "a1b2c3d4"


def full_version() -> str:
    """
    返回完整版本字符串，如：1.6.2+45 (a1b2c3d)
    如果没有构建号/提交号，则只返回基本版本。
    """
    v = __version__
    if __build__:
        v = f"{v}+{__build__}"
    if __commit__:
        v = f"{v} ({__commit__[:7]})"
    return v


if __name__ == "__main__":
    # 允许命令行快速查看版本：python -m version
    print(f"{__app_name__} v{full_version()}")
