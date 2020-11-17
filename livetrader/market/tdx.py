import asyncio
from asyncio import Event, sleep
from datetime import datetime
from typing import Optional

import pytz
from environs import Env
from livetrader.exceptions import RemoteError
from livetrader.market import MarketBase
from pytdx.exhq import TdxExHq_API, TDXParams
from pytdx.parser.ex_get_instrument_bars import GetInstrumentBars
from pytz import timezone


class TdxMarket(MarketBase):
    __market_name__ = 'TDX'
    __timeframe__ = '1MIN'

    __KLINE_TYPES = {
        1: TDXParams.KLINE_TYPE_1MIN,
        5: TDXParams.KLINE_TYPE_5MIN,
        15: TDXParams.KLINE_TYPE_15MIN,
        30: TDXParams.KLINE_TYPE_30MIN,
        60: TDXParams.KLINE_TYPE_1HOUR,
        1440: TDXParams.KLINE_TYPE_DAILY}

    def __init__(self, host: Optional[str] = None):
        self._env = env = Env()
        env.read_env()
        tdx_host = host if host else env.str(
            'TDX_HOST', asyncio.run(_select_host()))
        self._api = TdxExHq_API(heartbeat=True, multithread=True)
        self._ip, self._port = tdx_host.split(':')
        self._server_tz = timezone('Asia/Shanghai')
        self._pill = Event()
        self._market_mapping = dict(
            zip(["SHFE", "CZCE", "DCE", "CFFEX", "US"], [30, 28, 29, 47, 74]))

    def connect(self):
        if not self._api.connect(self._ip, int(self._port)):
            raise RemoteError('%s:%s connect error.' %
                              (self.ip, int(self.port)))
        self._market_list = list(
            self._api.to_df(
                self._api.get_markets()).market)

    async def watch_klines(self, symbol: str):
        market, code = symbol.split('.')
        last_kline = None
        while not self._pill.is_set():
            tdx_klines = self._get_instrument_bars(
                TDXParams.KLINE_TYPE_1MIN, self._market_mapping[market], code, 0, 10)
            # 这个地方处理的原因在于由于是轮询的，就有可能出现在轮询间隔的时间(这里是1秒)内，有一半时间属于上一根K线，有一半时间属于下一根K线，所以如果我们只看最新的K线的话，前一根K线的一部分数据可能就会丢失，因此这里判断一下前一根K线如果有更新，就先把前一根K线推送了，再推送下一根K线
            prev_kline = self._parse_kline(tdx_klines[-2])
            latest_kline = self._parse_kline(tdx_klines[-1])
            if last_kline and prev_kline['datetime'] == last_kline['datetime']:
                self.logger.debug('yield prev kline: %s' % prev_kline)
                yield prev_kline
            if last_kline != latest_kline:
                yield latest_kline
                self.logger.debug('yield latest kline: %s' % latest_kline)
                last_kline = latest_kline
            await sleep(1)

    async def get_kline_histories(self, symbol: str, from_ts: Optional[int] = None, to_ts: Optional[int] = None, limit: Optional[int] = None, timeframe: Optional[int] = 1):
        market, code = symbol.split('.')
        if self._market_mapping[market] in self._market_list:
            bars = []
            # 因为通达信的接口设计原因，所以from_ts 和 limit 至少有一个，然后 to_ts 最后做过滤是为了保证接口语义正确
            if from_ts is not None:
                idx = 0
                while len(bars) == 0 or bars[-1]['datetime'] >= from_ts:
                    bars += [
                        self._parse_kline(bar) for bar in reversed(
                            self._get_instrument_bars(
                                self.__class__.__KLINE_TYPES[timeframe],
                                self._market_mapping[market],
                                code, idx * 700, 700))]
                    idx += 1
                # 前面都是整700地取，所以有可能取到的数据会超过 from_ts,因此这里再做一次过滤
                bars = list(filter(lambda x: x['datetime'] >= from_ts, bars))
            elif limit is not None:
                for i in range(limit // 700):
                    bars += [
                        self._parse_kline(bar) for bar in reversed(
                            self._get_instrument_bars(
                                TDXParams.KLINE_TYPE_1MIN,
                                self._market_mapping[market],
                                code, i * 700, 700))]
                bars += [
                    self._parse_kline(bar) for bar in reversed(
                        self._get_instrument_bars(
                            TDXParams.KLINE_TYPE_1MIN,
                            self._market_mapping[market],
                            code, limit // 700 * 700,
                            limit % 700))]

            if to_ts:
                bars = list(filter(lambda x: x['datetime'] <= to_ts, bars))
            return reversed(bars)

    def disconnect(self):
        self._pill.set()
        self._api.disconnect()

    def _get_instrument_bars(self, category, market, code, start=0, count=700):
        while True:
            try:
                cmd = GetInstrumentBars(self._api.client, lock=self._api.lock)
                cmd.setParams(category, market, code, start=start, count=count)
                return cmd.call_api()
            except Exception as e:
                pass

    def _parse_kline(self, kline_tdx: dict) -> dict:
        dt = self._server_tz.localize(
            datetime.strptime(
                kline_tdx['datetime'],
                '%Y-%m-%d %H:%M')).astimezone(pytz.utc)
        return {
            'datetime': int(dt.timestamp() * 1000),
            'open': str(round(kline_tdx['open'], 2)),
            'high': str(round(kline_tdx['high'], 2)),
            'low': str(round(kline_tdx['low'], 2)),
            'close': str(round(kline_tdx['close'], 2)),
            'volume': kline_tdx['trade'],
        }


hosts = [('112.74.214.43', 7727), ('47.92.127.181', 7727),
         ('47.107.75.159', 7727), ('106.14.95.149', 7727), ('47.102.108.214', 7727)]


async def _select_host():
    async def ping(ip, port):
        await asyncio.open_connection(ip, port)
        return (ip, port)
    done, pendings = await asyncio.wait([asyncio.get_event_loop().create_task(ping(
        ip, port)) for ip, port in hosts], return_when=asyncio.FIRST_COMPLETED)
    for task in pendings:
        task.cancel()
    return done[0].result()
