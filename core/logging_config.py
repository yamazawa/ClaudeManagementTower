"""ログ出力の設定

サーバー・ワーカー・起動管理の各プロセスで共通の出力形式を設定する。
"""

import logging

from core.config import settings

LOG_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def configure_logging(level: str | None = None) -> None:
    """ルートロガーに時刻・レベル・ロガー名付きの出力を設定する

    既にハンドラが設定済みの場合、basicConfigの仕様により何もしない。
    """
    logging.basicConfig(
        level=(level or settings.log_level).upper(),
        format=LOG_FORMAT,
        datefmt=LOG_DATE_FORMAT,
    )
