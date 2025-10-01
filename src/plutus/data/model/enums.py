from enum import Enum


class QuoteType(Enum):
    REFERENCE = 'ref_price'
    CEILING = 'ceiling_price'
    FLOOR = 'floor_price'
    OPEN = 'open_price'
    CLOSE = 'close_price'
    BID_PRI_10 = 'bid_price_10'
    BID_QTY_10 = 'bid_qty_10'
    BID_PRI_9 = 'bid_price_9'
    BID_QTY_9 = 'bid_qty_9'
    BID_PRI_8 = 'bid_price_8'
    BID_QTY_8 = 'bid_qty_8'
    BID_PRI_7 = 'bid_price_7'
    BID_QTY_7 = 'bid_qty_7'
    BID_PRI_6 = 'bid_price_6'
    BID_QTY_6 = 'bid_qty_6'
    BID_PRI_5 = 'bid_price_5'
    BID_QTY_5 = 'bid_qty_5'
    BID_PRI_4 = 'bid_price_4'
    BID_QTY_4 = 'bid_qty_4'
    BID_PRI_3 = 'bid_price_3'
    BID_QTY_3 = 'bid_qty_3'
    BID_PRI_2 = 'bid_price_2'
    BID_QTY_2 = 'bid_qty_2'
    BID_PRI_1 = 'bid_price_1'
    BID_QTY_1 = 'bid_qty_1'
    LATEST_PRICE = 'latest_price'
    LATEST_QTY = 'latest_qty'
    REF_DIFF_ABS = 'ref_diff_abs'
    REF_DIFF_PCT = 'ref_diff_pct'
    ASK_PRI_1 = 'ask_price_1'
    ASK_QTY_1 = 'ask_qty_1'
    ASK_PRI_2 = 'ask_price_2'
    ASK_QTY_2 = 'ask_qty_2'
    ASK_PRI_3 = 'ask_price_3'
    ASK_QTY_3 = 'ask_qty_3'
    ASK_PRI_4 = 'ask_price_4'
    ASK_QTY_4 = 'ask_qty_4'
    ASK_PRI_5 = 'ask_price_5'
    ASK_QTY_5 = 'ask_qty_5'
    ASK_PRI_6 = 'ask_price_6'
    ASK_QTY_6 = 'ask_qty_6'
    ASK_PRI_7 = 'ask_price_7'
    ASK_QTY_7 = 'ask_qty_7'
    ASK_PRI_8 = 'ask_price_8'
    ASK_QTY_8 = 'ask_qty_8'
    ASK_PRI_9 = 'ask_price_9'
    ASK_QTY_9 = 'ask_qty_9'
    ASK_PRI_10 = 'ask_price_10'
    ASK_QTY_10 = 'ask_qty_10'
    TOTAL_MATCHED_QTY = 'total_matched_qty'
    HIGHEST_PRICE = 'highest_price'
    LOWEST_PRICE = 'lowest_price'
    AVG_PRICE = 'avg_price'
    FOREIGN_BUY_QTY = 'foreign_buy_qty'
    FOREIGN_SELL_QTY = 'foreign_sell_qty'
    FOREIGN_ROOM = 'foreign_room'
    MATURITY_DATE = 'maturity_date'
    LATEST_ESTIMATED_MATCHED_PRICE = 'latest_est_matched_price'
    SETTLEMENT_PRICE = 'settlement_price'
    OPEN_INTEREST = 'open_interest'


# A reusable mapping from a string value back to its QuoteType enum member
STRING_TO_QUOTETYPE_MAP = {member.value: member for member in QuoteType}

# A set of string keys for quote types that should be represented as Decimal
QUOTE_DECIMAL_ATTRIBUTES = {
    'ref_price',
    'ceiling_price',
    'floor_price',
    'open_price',
    'close_price',
    'bid_price_10',
    'bid_price_9',
    'bid_price_8',
    'bid_price_7',
    'bid_price_6',
    'bid_price_5',
    'bid_price_4',
    'bid_price_3',
    'bid_price_2',
    'bid_price_1',
    'latest_price',
    'ref_diff_abs',
    'ref_diff_pct',
    'ask_price_1',
    'ask_price_2',
    'ask_price_3',
    'ask_price_4',
    'ask_price_5',
    'ask_price_6',
    'ask_price_7',
    'ask_price_8',
    'ask_price_9',
    'ask_price_10',
    'highest_price',
    'lowest_price',
    'avg_price',
    'latest_est_matched_price',
    'settlement_price',
}
