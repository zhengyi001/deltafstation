"""
CCXT 数据获取模块

支持通过 ccxt 库从多个交易所（包括币安）下载加密货币 K 线数据。
从 backtest-frame 的 data_loader_util.py 迁移而来。

依赖安装：
    pip install ccxt pandas

使用示例：
    fetcher = CCXTDataFetcher()
    df = fetcher.fetch_klines(
        exchange="binance",
        symbol="BTC/USDT",
        interval="1h",
        start_date=datetime(2023, 1, 1),
        end_date=datetime(2024, 1, 1)
    )
    df.to_csv("BTCUSDT_1h.csv", index=False)
"""
import time
import pandas as pd
from datetime import datetime, timedelta
from typing import Optional, Tuple

try:
    import ccxt
except ImportError:
    raise ImportError(
        "CCXT is not installed. Please install it with: pip install ccxt"
    )


class CCXTDataFetcher:
    """基于 CCXT 的加密货币数据获取器"""

    def __init__(self, exchange: str = "binance"):
        """
        初始化数据获取器

        Args:
            exchange: 交易所名称（如 'binance', 'okx', 'huobi' 等）
        """
        self.exchange_name = exchange
        self.exchange = self._create_exchange(exchange)

    def _create_exchange(self, exchange_name: str):
        """创建交易所实例"""
        if exchange_name.lower() not in ccxt.exchanges:
            raise ValueError(f"不支持的交易所: {exchange_name}")

        # 获取交易所类
        exchange_class = getattr(ccxt, exchange_name)

        # 创建交易所实例（配置代理、超时等）
        exchange = exchange_class({
            'enableRateLimit': True,  # 启用速率限制
            'timeout': 30000,  # 30秒超时
            'options': {
                'defaultType': 'spot'  # 默认现货交易，如需合约可改为 'future'
            }
        })

        return exchange

    def fetch_klines(
        self,
        symbol: str,
        interval: str = "1h",
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: int = 1000
    ) -> pd.DataFrame:
        """
        获取 K 线数据

        Args:
            symbol: 交易对符号（如 'BTC/USDT'）
            interval: K线周期（如 '1m', '5m', '15m', '1h', '4h', '1d'）
            start_date: 起始时间（None 则从最早的可用数据开始）
            end_date: 结束时间（None 则到当前时间）
            limit: 单次请求的最大 K 线数量（默认 1000，根据交易所限制调整）

        Returns:
            DataFrame 包含以下列：
            - datetime: 日期时间（UTC）
            - open: 开盘价
            - high: 最高价
            - low: 最低价
            - close: 收盘价
            - volume: 成交量
        """
        # 转换为时间戳（毫秒）
        if start_date is None:
            since = None
        else:
            since = int(start_date.timestamp() * 1000)

        if end_date is None:
            end_date = datetime.utcnow()

        all_klines = []
        current_since = since
        batch_count = 0

        print(f"开始从 {self.exchange_name} 下载 {symbol} 数据...")
        print(f"  时间范围: {start_date or '最早'} ~ {end_date}")
        print(f"  K线周期: {interval}")

        while True:
            try:
                # 获取 K 线数据
                klines = self.exchange.fetch_ohlcv(
                    symbol=symbol,
                    timeframe=interval,
                    since=current_since,
                    limit=limit
                )

                if not klines:
                    break

                all_klines.extend(klines)
                batch_count += 1

                # 更新下一次请求的起始时间戳
                last_timestamp = klines[-1][0]
                current_since = last_timestamp + 1

                # 检查是否超过结束时间
                if end_date and last_timestamp >= int(end_date.timestamp() * 1000):
                    break

                # 打印进度
                print(f"  已下载 {len(all_klines)} 根 K 线...")

                # 避免触发速率限制
                time.sleep(self.exchange.rateLimit / 1000)

                # 安全限制：防止无限循环
                if batch_count > 1000:
                    print("  已达到最大批次数限制，停止下载")
                    break

            except Exception as e:
                print(f"  下载出错: {e}")
                print("  等待 5 秒后重试...")
                time.sleep(5)

        if not all_klines:
            print("  未获取到任何数据")
            return pd.DataFrame()

        print(f"✅ 下载完成！共获取 {len(all_klines)} 根 K 线")

        # 转换为 DataFrame
        df = pd.DataFrame(all_klines, columns=[
            'timestamp', 'open', 'high', 'low', 'close', 'volume'
        ])

        # 转换时间戳为 datetime（UTC）
        df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)

        # 删除 timestamp 列
        df.drop('timestamp', axis=1, inplace=True)

        # 转换数据类型
        df[['open', 'high', 'low', 'close', 'volume']] = df[
            ['open', 'high', 'low', 'close', 'volume']
        ].astype(float)

        # 重排列
        df = df[['datetime', 'open', 'high', 'low', 'close', 'volume']]

        return df

    def fetch_futures_klines(
        self,
        symbol: str = "BTC/USDT",
        interval: str = "1h",
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: int = 1000
    ) -> pd.DataFrame:
        """
        获取合约 K 线数据

        Args:
            symbol: 交易对符号（如 'BTC/USDT'）
            interval: K线周期
            start_date: 起始时间
            end_date: 结束时间
            limit: 单次请求的最大 K 线数量

        Returns:
            DataFrame 包含 datetime, open, high, low, close, volume 列
        """
        # 创建合约类型的交易所实例
        exchange_class = getattr(ccxt, self.exchange_name)
        exchange = exchange_class({
            'enableRateLimit': True,
            'timeout': 30000,
            'options': {
                'defaultType': 'future'  # 合约交易
            }
        })

        # 临时替换 exchange
        original_exchange = self.exchange
        self.exchange = exchange

        try:
            df = self.fetch_klines(
                symbol=symbol,
                interval=interval,
                start_date=start_date,
                end_date=end_date,
                limit=limit
            )
        finally:
            # 恢复原始 exchange
            self.exchange = original_exchange

        return df


def fetch_binance_btcusdt(
    interval: str = "1h",
    days: int = 365,
    futures: bool = False
) -> Tuple[pd.DataFrame, str]:
    """
    便捷函数：从币安获取 BTCUSDT 数据

    Args:
        interval: K线周期（如 '1h', '4h', '1d'）
        days: 获取最近多少天的数据
        futures: 是否获取合约数据

    Returns:
        (DataFrame, source_name) 元组
    """
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=days)

    fetcher = CCXTDataFetcher(exchange="binance")

    if futures:
        df = fetcher.fetch_futures_klines(
            symbol="BTC/USDT",
            interval=interval,
            start_date=start_date,
            end_date=end_date
        )
        source = "binance-futures"
    else:
        df = fetcher.fetch_klines(
            symbol="BTC/USDT",
            interval=interval,
            start_date=start_date,
            end_date=end_date
        )
        source = "binance-spot"

    return df, source


# 使用示例
if __name__ == "__main__":
    # 示例1：下载现货数据
    print("=" * 50)
    print("示例1：下载币安 BTCUSDT 现货数据（1小时周期，最近90天）")
    print("=" * 50)
    df_spot, source_spot = fetch_binance_btcusdt(
        interval="1h",
        days=90,
        futures=False
    )
    print(f"\n数据源: {source_spot}")
    print(f"数据行数: {len(df_spot)}")
    print(f"\n前5行数据:")
    print(df_spot.head())

    # 示例2：下载合约数据
    print("\n" + "=" * 50)
    print("示例2：下载币安 BTCUSDT 合约数据（4小时周期，最近180天）")
    print("=" * 50)
    df_futures, source_futures = fetch_binance_btcusdt(
        interval="4h",
        days=180,
        futures=True
    )
    print(f"\n数据源: {source_futures}")
    print(f"数据行数: {len(df_futures)}")
    print(f"\n后5行数据:")
    print(df_futures.tail())
