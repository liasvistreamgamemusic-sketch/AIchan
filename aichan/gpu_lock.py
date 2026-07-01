"""LLM(Vulkan)とTTS(ROCm)の推論呼び出しをまたいで直列化する共有ロック。

同一GPU上で異なるバックエンドが同時に推論すると不安定になりうるため
(RX 9070 XT + ROCmでの既知の不安定要因)、両者の実推論呼び出しはこの
ロックで確実に排他する。
"""
from __future__ import annotations

import threading

GPU_LOCK = threading.Lock()
