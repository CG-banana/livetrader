import logging

from livetrader.market import CachedMarket, DwxMarket, MarketService, TdxMarket
from livetrader.rpc import Server


def create_server():
    market = CachedMarket(
        DwxMarket(host='192.168.50.113'),
        mongodb_uri='mongodb://root:example@127.0.0.1:27016/?authMechanism=SCRAM-SHA-256')
    service = MarketService(market, ['FOREX.EURUSD'])
    server = Server(service)
    server.bind('ipc:///tmp/market')
    return server


if __name__ == "__main__":
    logging.basicConfig(format=' %(name)s :: %(levelname)-8s :: %(message)s')
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    server = create_server()
    server.run()
