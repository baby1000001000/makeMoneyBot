"""
工具模块 - 公共函数和配置加载
"""
import yaml
import logging
import hashlib
import hmac
import time
import json
import os
from datetime import datetime
from typing import Dict, Any, Optional

def load_config(config_path: str = "config.yaml") -> Dict[str, Any]:
    """加载配置文件"""
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    except Exception as e:
        raise Exception(f"加载配置文件失败: {e}")

def load_secrets() -> Dict[str, Any]:
    """
    安全地加载密钥配置，支持环境变量和secrets.json文件
    优先级：环境变量 > secrets.json
    """
    try:
        secrets = {}
        
        # 尝试从环境变量加载
        mexc_key = os.getenv('MEXC_API_KEY')
        mexc_secret = os.getenv('MEXC_SECRET_KEY')
        gate_key = os.getenv('GATE_API_KEY')
        gate_secret = os.getenv('GATE_SECRET_KEY')
        
        if mexc_key and mexc_secret:
            secrets['mexc'] = {
                'api_key': mexc_key,
                'secret_key': mexc_secret
            }
            print("✅ MEXC密钥从环境变量加载")
        
        if gate_key and gate_secret:
            secrets['gate'] = {
                'api_key': gate_key,
                'secret_key': gate_secret
            }
            print("✅ Gate密钥从环境变量加载")
        
        # 如果环境变量不完整，尝试从secrets.json加载
        if not secrets.get('mexc') or not secrets.get('gate'):
            print("⚠️ 环境变量不完整，尝试从secrets.json加载...")
            
            # 尝试加载secrets.json
            secrets_file = "secrets.json"
            if os.path.exists(secrets_file):
                try:
                    with open(secrets_file, 'r', encoding='utf-8') as f:
                        secrets_data = json.load(f)
                    
                    if not secrets.get('mexc') and 'mexc' in secrets_data:
                        secrets['mexc'] = secrets_data['mexc']
                        mexc_key = secrets['mexc'].get('api_key', '')
                        print(f"mexc_key:{mexc_key[:8]}...")
                    
                    if not secrets.get('gate') and 'gate' in secrets_data:
                        secrets['gate'] = secrets_data['gate']
                        gate_key = secrets['gate'].get('api_key', '')
                        print(f"gate_key:{gate_key[:8]}...")
                        
                except Exception as e:
                    print(f"⚠️ 读取secrets.json失败: {e}")
            else:
                print("⚠️ 未找到secrets.json文件")
            
            # 如果仍然没有加载到密钥，提示用户
            if not secrets.get('mexc') or not secrets.get('gate'):
                raise Exception("请在secrets.json中配置API密钥，或设置环境变量")
        
        # 验证必需的密钥
        if not secrets.get('mexc'):
            print("⚠️ 未配置MEXC API密钥")
        if not secrets.get('gate'):
            raise Exception("Gate API密钥配置缺失或无效")
        
        # 从config.yaml加载地址配置
        try:
            config = load_config("config.yaml")
            if 'addresses' in config:
                secrets['addresses'] = config['addresses']
            else:
                secrets['addresses'] = {}
        except Exception as e:
            print(f"⚠️ 无法加载地址配置: {e}")
            secrets['addresses'] = {}
        
        return secrets
        
    except Exception as e:
        raise Exception(f"加载密钥配置失败: {e}")

def setup_logging(config: Dict[str, Any]) -> logging.Logger:
    """设置日志配置"""
    log_config = config.get('logging', {})
    log_level = getattr(logging, log_config.get('level', 'INFO').upper())
    log_path = log_config.get('path', 'logs/')
    
    if not os.path.exists(log_path):
        os.makedirs(log_path)
    
    # 设置主日志
    logging.basicConfig(
        level=log_level,
        format='[%(asctime)s][%(levelname)s][%(name)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        handlers=[
            logging.FileHandler(os.path.join(log_path, 'arbitrage.log'), encoding='utf-8'),
            logging.StreamHandler()
        ]
    )
    
    return logging.getLogger('ArbitrageBot')

def generate_trade_id() -> str:
    """生成交易流水ID"""
    timestamp = int(time.time() * 1000)
    return str(timestamp)

def format_timestamp(timestamp: Optional[float] = None) -> str:
    """格式化时间戳为标准格式"""
    if timestamp is None:
        timestamp = time.time()
    return datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S:%f')[:-3]

def calculate_spread_bps(buy_price: float, sell_price: float) -> float:
    """计算价差基点"""
    if buy_price <= 0:
        return 0
    return ((sell_price - buy_price) / buy_price) * 10000

def calculate_profit(
    amount: float, 
    buy_price: float, 
    sell_price: float,
    buy_fee_bps: float,
    sell_fee_bps: float,
    transfer_fee: float = 0
) -> tuple:
    """
    计算套利利润
    返回: (净利润, 总成本, 总收入)
    """
    # 买入成本 = 金额 + 手续费
    buy_cost = amount * (1 + buy_fee_bps / 10000)
    
    # 卖出收入 = (金额 / 买价 * 卖价) - 手续费
    sell_amount = amount / buy_price
    sell_income = sell_amount * sell_price * (1 - sell_fee_bps / 10000)
    
    # 净利润 = 卖出收入 - 买入成本 - 转账费用
    net_profit = sell_income - buy_cost - transfer_fee
    
    return net_profit, buy_cost, sell_income

class TradeLogger:
    """交易日志记录器"""
    
    def __init__(self, log_path: str = "logs/"):
        self.log_path = log_path
        self.trade_logger = self._setup_trade_logger()
        self.fund_logger = self._setup_fund_logger()
    
    def _setup_trade_logger(self):
        """设置交易日志"""
        logger = logging.getLogger('TradeLogger')
        handler = logging.FileHandler(
            os.path.join(self.log_path, 'trade_history.log'), 
            encoding='utf-8'
        )
        formatter = logging.Formatter('[%(asctime)s][%(message)s]')
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        return logger
    
    def _setup_fund_logger(self):
        """设置资金流水日志"""
        logger = logging.getLogger('FundLogger')
        handler = logging.FileHandler(
            os.path.join(self.log_path, 'fund_flow.log'),
            encoding='utf-8'
        )
        formatter = logging.Formatter('[%(asctime)s][%(message)s]')
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        return logger
    
    def log_trade(self, trade_id: str, exchange: str, action: str, details: str):
        """记录交易日志"""
        message = f"[{trade_id}]{exchange}-> {action}: {details}"
        self.trade_logger.info(message)
        
    def log_fund_flow(self, trade_id: str, exchange: str, action: str, 
                     amount: float, currency: str, details: str = ""):
        """记录资金流水"""
        message = f"[{trade_id}]{exchange}-> {action} {amount} {currency}. {details}"
        self.fund_logger.info(message)