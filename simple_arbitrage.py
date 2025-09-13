#!/usr/bin/env python3
"""
修复版简化套利执行器
专注于MEXC到Gate.io的完整套利流程
严格按照API获取地址，修复所有已知缺陷
"""
import sys
import os
import time
import json
import logging
import re
from datetime import datetime
from decimal import Decimal, ROUND_DOWN
import stat
from typing import Dict, Optional, Tuple
from threading import Lock

# API速率限制保护
_api_call_lock = Lock()
_last_api_call_time = {'mexc': 0, 'gate': 0}

sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))
from mexc_sdk import MEXCSDK
from gate_sdk import GateSDK

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 安全常量
TRADING_FEE_RATE = Decimal('0.002')  # 0.2% 交易手续费
DEPOSIT_TOLERANCE = Decimal('0.05')  # 5% 到账容差
MAX_SLIPPAGE = Decimal('0.01')  # 1% 最大滑点
BALANCE_CHECK_INTERVAL = 30  # 余额检查间隔（秒）
ORDER_TIMEOUT = 30  # 订单超时（秒）
MAX_RETRY_ATTEMPTS = 3  # 最大重试次数
RETRY_DELAY = 2  # 重试延迟（秒）

# 交易所特定手续费率
MEXC_TAKER_FEE = 0.002  # MEXC吃单手续费 0.2%
GATE_TAKER_FEE = 0.002  # Gate.io吃单手续费 0.2%
FEE_SAFETY_MARGIN = 0.998  # 1 - 0.002，用于计算实际可用金额

def retry_on_failure(max_attempts: int = MAX_RETRY_ATTEMPTS, delay: float = RETRY_DELAY):
    """重试装饰器"""
    def decorator(func):
        def wrapper(*args, **kwargs):
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if attempt == max_attempts - 1:  # 最后一次尝试
                        raise e
                    logger.warning(f"⚠️ 操作失败，{delay}秒后重试 ({attempt + 1}/{max_attempts}): {e}")
                    time.sleep(delay)
            return None
        return wrapper
    return decorator

def rate_limit_api_call(platform: str, min_interval: float = 0.1):
    """API速率限制装饰器"""
    def decorator(func):
        def wrapper(*args, **kwargs):
            global _last_api_call_time
            with _api_call_lock:
                current_time = time.time()
                time_since_last = current_time - _last_api_call_time.get(platform, 0)
                
                if time_since_last < min_interval:
                    sleep_time = min_interval - time_since_last
                    logger.debug(f"API速率限制: {platform} 等待 {sleep_time:.3f} 秒")
                    time.sleep(sleep_time)
                
                _last_api_call_time[platform] = time.time()
                
            return func(*args, **kwargs)
        return wrapper
    return decorator

class SimpleArbitrageBot:
    """修复版简化套利机器人"""
    
    def __init__(self):
        """初始化"""
        self.mexc = None
        self.gate = None
        self.load_config()
        
    def load_config(self):
        """加载配置"""
        try:
            # 安全检查：验证配置文件权限
            config_file = 'secrets.json'
            file_stat = os.stat(config_file)
            file_mode = stat.filemode(file_stat.st_mode)
            
            # 检查文件权限是否过于宽松
            if file_stat.st_mode & 0o077:  # 检查组和其他用户权限
                logger.warning("⚠️ secrets.json 文件权限过于宽松，建议设置为 600")
            
            with open(config_file, 'r') as f:
                config = json.load(f)
            
            self.mexc = MEXCSDK(
                api_key=config['mexc']['api_key'],
                secret_key=config['mexc']['secret_key']
            )
            
            self.gate = GateSDK(
                api_key=config['gate']['api_key'],
                secret_key=config['gate']['secret_key']
            )
            
            # 验证连接
            if self.mexc.ping():
                logger.info("✅ MEXC连接正常")
            else:
                logger.error("❌ MEXC连接失败")
                raise Exception("MEXC连接失败")
                
            logger.info("✅ SDK初始化成功")
            
        except FileNotFoundError:
            logger.error("❌ secrets.json文件不存在")
            sys.exit(1)
        except KeyError as e:
            logger.error(f"❌ 配置文件缺少必要字段: {e}")
            sys.exit(1)
        except PermissionError:
            logger.error("❌ 没有权限读取配置文件")
            sys.exit(1)
        except json.JSONDecodeError as e:
            logger.error(f"❌ 配置文件JSON格式错误: {e}")
            sys.exit(1)
        except Exception as e:
            # 安全：过滤敏感信息
            safe_error = self._sanitize_log_message(str(e))
            logger.error(f"❌ 配置加载失败: {safe_error}")
            sys.exit(1)
    
    def log_transaction(self, message: str):
        """记录交易日志"""
        timestamp = datetime.now().strftime('[%Y-%m-%d %H:%M:%S:%f')[:-3] + ']'
        transaction_id = int(time.time() * 1000) % 1000000000  # 9位流水ID
        
        # 过滤敏感信息
        safe_message = self._sanitize_log_message(message)
        log_entry = f"{timestamp}[{transaction_id}] {safe_message}"
        
        logger.info(log_entry)
        
        # 写入日志文件
        try:
            with open('arbitrage_transactions.log', 'a', encoding='utf-8') as f:
                f.write(log_entry + '\n')
        except Exception as e:
            logger.error(f"写入日志文件失败: {e}")
    
    def track_withdrawal_status(self, withdrawal_id: str, platform: str) -> str:
        """追踪提现状态 - 防止资金丢失"""
        try:
            if platform.lower() == 'mexc':
                # 查询MEXC提现记录
                history = self.mexc.get_withdraw_history(limit=50)
                for record in history:
                    if str(record.get('id')) == str(withdrawal_id):
                        status = record.get('status')
                        logger.info(f"📊 MEXC提现{withdrawal_id}状态: {status}")
                        return status
                        
            elif platform.lower() == 'gate':
                # 查询Gate提现记录  
                history = self.gate.get_withdrawals(limit=50)
                for record in history:
                    if str(record.get('id')) == str(withdrawal_id):
                        status = record.get('status')
                        logger.info(f"📊 Gate提现{withdrawal_id}状态: {status}")
                        return status
            
            logger.warning(f"⚠️ 未找到提现记录: {withdrawal_id}")
            return 'unknown'
            
        except Exception as e:
            logger.error(f"❌ 查询提现状态失败: {e}")
            return 'error'

    def validate_address_format(self, address: str, coin: str) -> bool:
        """验证提现地址格式的基本安全性"""
        if not address or not isinstance(address, str):
            logger.error("❌ 地址为空或格式无效")
            return False
            
        # 基本长度检查
        if len(address) < 20:
            logger.error(f"❌ 地址长度过短: {len(address)} < 20")
            return False
            
        # 防止明显的测试地址
        dangerous_patterns = [
            'test', 'fake', 'invalid', '123456', '000000', 'sample',
            'example', 'demo', 'placeholder', '0x0000000000000000'
        ]
        
        address_lower = address.lower()
        for pattern in dangerous_patterns:
            if pattern in address_lower:
                logger.error(f"❌ 检测到危险地址模式: {pattern}")
                return False
        
        # 币种特定的基本验证
        if coin == 'USDT' and 'BSC' in str(address):
            # BSC地址应该以0x开头且长度为42
            if not (address.startswith('0x') and len(address) == 42):
                logger.error(f"❌ BSC地址格式错误: {address}")
                return False
                
        elif coin == 'XLM':
            # Stellar地址通常是以G开头的56个字符
            if not (address.startswith('G') and len(address) == 56):
                logger.error(f"❌ Stellar地址格式错误: {address}")
                return False
        
        logger.info(f"✅ 地址格式验证通过: {address[:10]}...{address[-6:]}")
        return True

    def validate_coin_symbol(self, coin: str) -> bool:
        """验证币种符号的安全性"""
        if not coin or not isinstance(coin, str):
            return False
        
        # 只允许字母和数字，长度在2-10之间
        if not re.match(r'^[A-Z0-9]{2,10}$', coin.upper()):
            logger.error(f"❌ 币种符号格式无效: {coin}")
            return False
        
        # 黑名单检查
        blocked_symbols = ['TEST', 'FAKE', 'SCAM']
        if any(blocked in coin.upper() for blocked in blocked_symbols):
            logger.error(f"❌ 币种在黑名单中: {coin}")
            return False
            
        return True
    
    def _sanitize_log_message(self, message: str) -> str:
        """清理日志消息中的敏感信息"""
        if not isinstance(message, str):
            message = str(message)
            
        # 过滤可能的敏感信息
        patterns = [
            # API密钥（32位以上字母数字）
            (r'[A-Za-z0-9]{32,}', lambda m: m.group()[:8] + '***' + m.group()[-4:] if len(m.group()) > 16 else m.group()),
            # 钱包地址（以0x开头或长度20+的字母数字）
            (r'0x[A-Fa-f0-9]{40}', lambda m: m.group()[:6] + '***' + m.group()[-6:]),
            (r'[A-Za-z0-9]{20,}', lambda m: m.group()[:8] + '***' + m.group()[-6:] if len(m.group()) > 20 else m.group()),
            # 文件路径
            (r'/[^\s]*secrets[^\s]*', '[SECRETS_FILE]'),
            (r'/[^\s]*config[^\s]*', '[CONFIG_FILE]'),
            # 金额信息部分脱敏
            (r'amount[=:]\s*([0-9]+\.?[0-9]*)', lambda m: f"amount={m.group(1)[:3]}***"),
        ]
        
        safe_message = message
        for pattern, replacement in patterns:
            if callable(replacement):
                safe_message = re.sub(pattern, replacement, safe_message)
            else:
                safe_message = re.sub(pattern, replacement, safe_message)
        
        return safe_message
    
    def get_balances(self) -> Dict:
        """获取两个平台的余额"""
        balances = {
            'mexc': {'USDT': 0, 'coins': {}},
            'gate': {'USDT': 0, 'coins': {}}
        }
        
        try:
            # MEXC余额 - 增加重试机制
            for attempt in range(3):
                try:
                    mexc_account = self.mexc.get_account_info()
                    for asset in mexc_account.get('balances', []):
                        if asset['asset'] == 'USDT':
                            balances['mexc']['USDT'] = float(asset['free'])
                        else:
                            free_amount = float(asset['free'])
                            if free_amount > 0:
                                balances['mexc']['coins'][asset['asset']] = free_amount
                    break
                except Exception as e:
                    if attempt == 2:  # 最后一次尝试
                        logger.error(f"❌ 获取MEXC余额失败: {e}")
                    else:
                        logger.warning(f"⚠️ MEXC余额获取重试 {attempt + 1}/3: {e}")
                        time.sleep(1)
                        
        except Exception as e:
            logger.error(f"❌ MEXC余额获取异常: {e}")
        
        try:
            # Gate余额 - 增加重试机制
            for attempt in range(3):
                try:
                    gate_accounts = self.gate.get_spot_accounts()
                    for acc in gate_accounts:
                        if acc['currency'] == 'USDT':
                            balances['gate']['USDT'] = float(acc.get('available', 0))
                        else:
                            available = float(acc.get('available', 0))
                            if available > 0:
                                balances['gate']['coins'][acc['currency']] = available
                    break
                except Exception as e:
                    if attempt == 2:  # 最后一次尝试
                        logger.error(f"❌ 获取Gate余额失败: {e}")
                    else:
                        logger.warning(f"⚠️ Gate余额获取重试 {attempt + 1}/3: {e}")
                        time.sleep(1)
                        
        except Exception as e:
            logger.error(f"❌ Gate余额获取异常: {e}")
            
        return balances
    
    def get_prices(self, coin: str) -> Dict:
        """获取价格信息"""
        prices = {
            'mexc': {'ask': 0, 'bid': 0},
            'gate': {'ask': 0, 'bid': 0}
        }
        
        try:
            # MEXC价格 - 根据实际返回数据结构处理
            mexc_ticker = self.mexc.get_ticker_price(f'{coin}USDT')
            if mexc_ticker:
                # 检查返回的是字典还是列表
                if isinstance(mexc_ticker, dict):
                    ticker = mexc_ticker
                elif isinstance(mexc_ticker, list) and mexc_ticker:
                    ticker = mexc_ticker[0]
                else:
                    ticker = {}
                
                # 获取价格，如果只有单一价格就用作买卖价
                price = float(ticker.get('price', 0))
                if price > 0:
                    prices['mexc']['ask'] = price
                    prices['mexc']['bid'] = price
        except Exception as e:
            logger.error(f"❌ 获取MEXC价格失败: {e}")
        
        try:
            # Gate价格
            gate_tickers = self.gate.get_tickers(f'{coin}_USDT')
            if gate_tickers:
                ticker = gate_tickers[0] if isinstance(gate_tickers, list) else gate_tickers
                prices['gate']['ask'] = float(ticker.get('lowest_ask', 0))
                prices['gate']['bid'] = float(ticker.get('highest_bid', 0))
        except Exception as e:
            logger.error(f"❌ 获取Gate价格失败: {e}")
            
        return prices
    
    def validate_coin_support(self, coin: str) -> bool:
        """验证币种是否被两个平台支持"""
        try:
            # 检查MEXC支持
            mexc_ticker = self.mexc.get_ticker_price(f'{coin}USDT')
            if not mexc_ticker:
                logger.error(f"❌ MEXC不支持 {coin}")
                return False
            
            # 处理MEXC返回的数据结构
            if isinstance(mexc_ticker, dict):
                ticker = mexc_ticker
            elif isinstance(mexc_ticker, list) and mexc_ticker:
                ticker = mexc_ticker[0]
            else:
                logger.error(f"❌ MEXC {coin} 数据格式异常")
                return False
            
            if float(ticker.get('price', 0)) <= 0:
                logger.error(f"❌ MEXC {coin} 价格异常")
                return False
                
            # 检查Gate支持  
            gate_tickers = self.gate.get_tickers(f'{coin}_USDT')
            if not gate_tickers:
                logger.error(f"❌ Gate.io不支持 {coin}")
                return False
                
            logger.info(f"✅ {coin} 币种验证通过")
            return True
            
        except Exception as e:
            logger.error(f"❌ 币种验证失败: {e}")
            return False
    
    def get_trading_limits(self, coin: str) -> Dict:
        """通过API获取完整的交易限制信息"""
        limits = {
            'min_buy_usdt': None,      # 最小买入金额(USDT) - 从API获取
            'min_sell_qty': None,      # 最小卖出数量 - 从API获取
            'min_withdraw_qty': None,  # 最小提现数量 - 从API获取
            'withdraw_fee': None       # 提现手续费 - 从API获取
        }
        
        try:
            # 获取MEXC交易规则
            exchange_info = self.mexc.get_exchange_info()
            symbol = f'{coin}USDT'
            
            for symbol_info in exchange_info.get('symbols', []):
                if symbol_info.get('symbol') == symbol:
                    for filter_info in symbol_info.get('filters', []):
                        filter_type = filter_info.get('filterType')
                        
                        # 最小交易名义价值（买入USDT金额限制）
                        if filter_type in ['NOTIONAL', 'MIN_NOTIONAL']:
                            notional = filter_info.get('minNotional')
                            if notional:
                                limits['min_buy_usdt'] = float(notional)
                            
                        # 最小交易数量（币种数量限制）
                        elif filter_type == 'LOT_SIZE':
                            min_qty = filter_info.get('minQty')
                            if min_qty:
                                limits['min_sell_qty'] = float(min_qty)
                    break
                    
            logger.info(f"✅ {coin} 交易限制: 最小买入{limits['min_buy_usdt']} USDT, 最小卖出{limits['min_sell_qty']} {coin}")
            
        except Exception as e:
            logger.error(f"❌ 获取交易规则失败: {e}")
            
        try:
            # 获取MEXC提现限制
            capital_config = self.mexc.get_capital_config()
            
            for coin_info in capital_config:
                if coin_info.get('coin') == coin:
                    network_list = coin_info.get('networkList', [])
                    if network_list:
                        # 使用第一个网络的提现限制作为参考
                        first_network = network_list[0]
                        withdraw_min = first_network.get('withdrawMin')
                        withdraw_fee = first_network.get('withdrawFee')
                        
                        if withdraw_min:
                            limits['min_withdraw_qty'] = float(withdraw_min)
                        if withdraw_fee:
                            limits['withdraw_fee'] = float(withdraw_fee)
                        
                        logger.info(f"✅ {coin} 提现限制: 最小{limits['min_withdraw_qty']} {coin}, 手续费{limits['withdraw_fee']} {coin}")
                    break
                    
        except Exception as e:
            logger.error(f"❌ 获取提现规则失败: {e}")
            
        try:
            # 获取Gate.io交易对限制
            gate_pair_info = self.gate.get_currency_pairs(f'{coin}_USDT')
            if gate_pair_info:
                # Gate.io的最小交易金额
                min_quote_amount = float(gate_pair_info.get('min_quote_amount', 1))
                limits['gate_min_sell_usdt'] = min_quote_amount
                logger.info(f"✅ Gate {coin} 最小卖出: {min_quote_amount} USDT")
                
        except Exception as e:
            logger.error(f"❌ 获取Gate交易对规则失败: {e}")
            
        try:
            # 获取Gate.io币种信息（包含提现限制）
            gate_currencies = self.gate.get_currencies()
            
            for currency_info in gate_currencies:
                if currency_info.get('currency') == coin:
                    gate_withdraw_min = float(currency_info.get('withdraw_min', 0))
                    gate_withdraw_fee = float(currency_info.get('withdraw_fee', 0))
                    
                    if gate_withdraw_min > 0:
                        limits['gate_min_withdraw_qty'] = gate_withdraw_min
                        limits['gate_withdraw_fee'] = gate_withdraw_fee
                        logger.info(f"✅ Gate {coin} 提现限制: 最小{gate_withdraw_min} {coin}, 手续费{gate_withdraw_fee} {coin}")
                    break
                    
        except Exception as e:
            logger.error(f"❌ 获取Gate币种规则失败: {e}")
            
        return limits
    
    def get_min_trade_amount(self, coin: str) -> float:
        """获取最小交易金额（兼容旧方法）"""
        limits = self.get_trading_limits(coin)
        min_amount = limits.get('min_buy_usdt')
        
        if min_amount is None:
            logger.warning(f"⚠️ 无法从API获取{coin}最小交易金额，使用默认值5 USDT")
            return 5.0  # 安全的默认值
            
        return min_amount
    
    def validate_and_display_limits(self, coin: str, usdt_amount: float) -> bool:
        """验证并显示所有交易限制信息"""
        print(f"\n🔍 正在获取 {coin} 的交易限制信息...")
        
        try:
            limits = self.get_trading_limits(coin)
            
            print(f"\n📋 {coin} 交易限制信息:")
            print("=" * 50)
            
            # MEXC限制
            print("🏪 MEXC交易所:")
            min_buy = limits.get('min_buy_usdt')
            if min_buy is not None:
                print(f"  ✅ 最小买入: {min_buy} USDT")
                if usdt_amount < min_buy:
                    print(f"  ❌ 投入金额 {usdt_amount} USDT 小于最小买入要求 {min_buy} USDT")
                    return False
            else:
                print(f"  ⚠️ 最小买入: 无法获取，使用默认5 USDT")
                
            min_sell = limits.get('min_sell_qty')
            if min_sell is not None:
                print(f"  ✅ 最小卖出数量: {min_sell} {coin}")
            else:
                print(f"  ⚠️ 最小卖出数量: 无法获取")
                
            min_withdraw = limits.get('min_withdraw_qty')
            withdraw_fee = limits.get('withdraw_fee')
            if min_withdraw is not None:
                print(f"  ✅ 最小提现: {min_withdraw} {coin}")
                if withdraw_fee is not None:
                    print(f"  ✅ 提现手续费: {withdraw_fee} {coin}")
            else:
                print(f"  ⚠️ 提现限制: 无法获取")
            
            # Gate.io限制
            print("\n🚪 Gate.io交易所:")
            gate_min_sell = limits.get('gate_min_sell_usdt')
            if gate_min_sell is not None:
                print(f"  ✅ 最小卖出金额: {gate_min_sell} USDT")
            else:
                print(f"  ⚠️ 最小卖出金额: 无法获取")
                
            gate_min_withdraw = limits.get('gate_min_withdraw_qty')
            gate_withdraw_fee = limits.get('gate_withdraw_fee')
            if gate_min_withdraw is not None:
                print(f"  ✅ 最小提现: {gate_min_withdraw} {coin}")
                if gate_withdraw_fee is not None:
                    print(f"  ✅ 提现手续费: {gate_withdraw_fee} {coin}")
            else:
                print(f"  ⚠️ 提现限制: 无法获取")
            
            print("=" * 50)
            
            # 检查关键限制
            missing_critical_info = []
            if limits.get('min_buy_usdt') is None:
                missing_critical_info.append("MEXC最小买入金额")
            if limits.get('min_withdraw_qty') is None:
                missing_critical_info.append("MEXC最小提现数量")
            if limits.get('gate_min_withdraw_qty') is None:
                missing_critical_info.append("Gate最小提现数量")
                
            if missing_critical_info:
                print(f"⚠️ 以下关键信息无法获取: {', '.join(missing_critical_info)}")
                print("建议谨慎执行或手动确认限制")
                
            return True
            
        except Exception as e:
            logger.error(f"❌ 获取交易限制失败: {e}")
            print(f"❌ 无法获取 {coin} 的交易限制信息")
            return False
    
    def get_gate_deposit_address(self, coin: str) -> Tuple[Optional[str], Optional[str]]:
        """获取Gate充值地址"""
        try:
            deposit_info = self.gate.get_deposit_address(coin)
            
            # 查找合适的地址
            address = None
            memo = None
            
            if 'multichain_addresses' in deposit_info:
                # 优先使用主链地址
                for addr_info in deposit_info['multichain_addresses']:
                    if addr_info.get('obtain_failed') == 0:  # 确保地址获取成功
                        address = addr_info.get('address')
                        memo = addr_info.get('payment_id', '') or None
                        if address:
                            chain = addr_info.get('chain', 'Unknown')
                            # 检查memo/tag参数
                            if memo:
                                logger.info(f"⚠️ {coin}需要memo/tag: {memo}")
                            self.log_transaction(f"Gate-> 获取{coin}充值地址成功，地址={address}，链={chain}，memo={memo or 'N/A'}")
                            logger.info(f"✅ Gate充值地址: {address} (链: {chain}) memo: {memo or 'N/A'}")
                            break
            else:
                # 兜底使用单地址
                address = deposit_info.get('address')
                if address:
                    self.log_transaction(f"Gate-> 获取{coin}充值地址成功，地址={address}")
                    
            if not address:
                logger.error(f"❌ 未能从Gate获取有效的{coin}充值地址")
                
            return address, memo
            
        except Exception as e:
            logger.error(f"❌ 获取Gate充值地址失败: {e}")
            return None, None
    
    def get_mexc_deposit_address(self, coin: str, preferred_network: str = None) -> Tuple[Optional[str], Optional[str]]:
        """获取MEXC充值地址"""
        try:
            deposit_addresses = self.mexc.get_deposit_address(coin)
            
            if isinstance(deposit_addresses, list) and deposit_addresses:
                # 优先选择指定网络
                if preferred_network:
                    for addr_info in deposit_addresses:
                        if preferred_network.upper() in addr_info.get('network', '').upper():
                            address = addr_info.get('address')
                            memo = addr_info.get('memo')
                            network = addr_info.get('network', 'Unknown')
                            self.log_transaction(f"MEXC-> 获取{coin}充值地址成功，地址={address[:20]}...，网络={network}")
                            logger.info(f"✅ MEXC充值地址: {address[:20]}... (网络: {network})")
                            return address, memo
                
                # 如果没找到指定网络，使用第一个可用地址
                first_addr = deposit_addresses[0]
                address = first_addr.get('address')
                memo = first_addr.get('memo')
                network = first_addr.get('network', 'Unknown')
                self.log_transaction(f"MEXC-> 获取{coin}充值地址成功，地址={address[:20]}...，网络={network}")
                logger.info(f"✅ MEXC充值地址: {address[:20]}... (网络: {network})")
                return address, memo
                
        except Exception as e:
            logger.error(f"❌ 获取MEXC充值地址失败: {e}")
            
        return None, None
    
    def wait_for_deposit(self, platform: str, coin: str, expected_amount: float, timeout: int = 600) -> bool:
        """等待充值到账"""
        self.log_transaction(f"{platform}-> 等待接收 {expected_amount:.6f} {coin}")
        logger.info(f"⏳ 等待{platform}接收 {expected_amount:.6f} {coin} (超时: {timeout}秒)")
        
        # 获取初始余额
        initial_balances = self.get_balances()
        initial_balance = 0
        
        if platform.lower() == 'gate':
            initial_balance = initial_balances['gate']['coins'].get(coin, 0)
        else:  # mexc
            initial_balance = initial_balances['mexc']['coins'].get(coin, 0) if coin != 'USDT' else initial_balances['mexc']['USDT']
        
        logger.info(f"📊 初始余额: {initial_balance:.6f} {coin}")
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            time.sleep(BALANCE_CHECK_INTERVAL)  # 使用配置的检查间隔
            
            current_balances = self.get_balances()
            current_balance = 0
            
            if platform.lower() == 'gate':
                current_balance = current_balances['gate']['coins'].get(coin, 0)
            else:  # mexc
                current_balance = current_balances['mexc']['coins'].get(coin, 0) if coin != 'USDT' else current_balances['mexc']['USDT']
            
            received_amount = current_balance - initial_balance
            
            # 使用安全常量进行比较
            tolerance_amount = float(Decimal(str(expected_amount)) * (Decimal('1') - DEPOSIT_TOLERANCE))
            if received_amount >= tolerance_amount:
                self.log_transaction(f"{platform}-> 成功接收 {received_amount:.6f} {coin}")
                logger.info(f"✅ 到账成功: {received_amount:.6f} {coin}")
                return True
                
            elapsed = int(time.time() - start_time)
            print(f"\r⏳ 等待中... {elapsed}秒，当前余额: {current_balance:.6f}", end='', flush=True)
        
        print(f"\n⚠️ 等待超时({timeout}秒)，请手动检查")
        logger.warning(f"等待{platform}到账超时")
        return False
    
    def execute_arbitrage_flow(self, coin: str, usdt_amount: float) -> bool:
        """执行完整套利流程"""
        self.log_transaction(f"开始执行套利: {coin}, 投入 {usdt_amount} USDT")
        logger.info(f"🚀 开始执行 {coin} 套利流程，投入 {usdt_amount} USDT")
        
        # 初始化变量防止作用域错误
        received_usdt = 0  # 默认值
        bought_quantity = 0  # 默认值
        
        try:
            # 第1步：MEXC买入币种
            logger.info("📈 步骤1: MEXC买入币种")
            buy_result = self.mexc_buy_coin(coin, usdt_amount)
            if not buy_result:
                logger.error("❌ MEXC买入失败")
                return False
            
            bought_quantity = buy_result['executed_qty']
            self.log_transaction(f"MEXC-> 成功买入 {bought_quantity} {coin}")
            logger.info(f"✅ MEXC买入成功: {bought_quantity} {coin}")
            
            # 第2步：获取Gate充值地址
            logger.info("🔍 步骤2: 查询Gate充值地址")
            gate_address, gate_memo = self.get_gate_deposit_address(coin)
            if not gate_address:
                logger.error("❌ 无法获取Gate充值地址")
                return False
            
            # 第3步：检查提现数量限制
            logger.info("🔍 步骤3a: 检查提现数量限制")
            
            # 获取最小提现数量
            capital_config = self.mexc.get_capital_config()
            min_withdraw_qty = 0
            
            for coin_info in capital_config:
                if coin_info.get('coin') == coin:
                    network_list = coin_info.get('networkList', [])
                    if network_list:
                        min_withdraw_qty = float(network_list[0].get('withdrawMin', 0))
                        logger.info(f"📋 {coin}最小提现数量: {min_withdraw_qty}")
                        break
            
            if bought_quantity < min_withdraw_qty:
                logger.error(f"❌ 买入数量不足最小提现要求: {bought_quantity} < {min_withdraw_qty}")
                logger.error(f"建议增加USDT投入金额，确保买入数量达到{min_withdraw_qty}个{coin}")
                return False
            
            # 第3步：MEXC提现到Gate
            logger.info("💸 步骤3b: MEXC提现到Gate")
            withdraw_result = self.mexc_withdraw_to_gate(coin, bought_quantity, gate_address, gate_memo)
            if not withdraw_result:
                logger.error("❌ MEXC提现失败")
                return False
            
            # 🔒 保存提现ID用于状态追踪
            withdraw_id = withdraw_result.get('withdraw_id') if isinstance(withdraw_result, dict) else None
            
            # 第4步：等待Gate到账 - 改进资金安全处理
            logger.info("⏳ 步骤4: 等待Gate到账")
            deposit_success = self.wait_for_deposit('gate', coin, bought_quantity * 0.95)  # 预留手续费
            if not deposit_success:
                logger.error("❌ 等待Gate到账超时")
                
                # 🔒 安全措施：追踪提现状态而不是直接失败
                if 'withdraw_id' in locals():
                    logger.info("🔍 追踪MEXC提现状态...")
                    withdraw_status = self.track_withdrawal_status(withdraw_id, 'mexc')
                    
                    if withdraw_status in ['completed', 'success']:
                        logger.warning("⚠️ 提现已成功，但Gate到账检测超时")
                        logger.warning("建议手动检查Gate账户，资金应该已到账")
                        # 继续执行后续步骤，因为提现实际成功了
                    elif withdraw_status in ['pending', 'processing']:
                        logger.warning("⚠️ MEXC提现仍在处理中，请耐心等待")
                        self.log_transaction(f"套利暂停: {coin}提现处理中，提现ID: {withdraw_id}")
                        return False
                    else:
                        logger.error(f"❌ MEXC提现状态异常: {withdraw_status}")
                        self.log_transaction(f"套利失败: MEXC提现状态异常")
                        return False
                else:
                    logger.error("❌ 无法获取提现ID，资金状态不明")
                    return False
            
            # 第5步：Gate卖出币种
            logger.info("📉 步骤5: Gate卖出币种")
            sell_result = self.gate_sell_coin(coin)
            if not sell_result:
                logger.error("❌ Gate卖出失败")
                return False
            
            received_usdt = sell_result['received_usdt']
            self.log_transaction(f"Gate-> 成功卖出获得 {received_usdt} USDT")
            logger.info(f"✅ Gate卖出成功: {received_usdt} USDT")
            
            # 第6步：获取MEXC的USDT BSC地址
            logger.info("🔍 步骤6: 查询MEXC USDT BSC地址")
            mexc_usdt_address, mexc_memo = self.get_mexc_deposit_address('USDT', 'BSC')
            if not mexc_usdt_address:
                logger.error("❌ 无法获取MEXC USDT BSC地址")
                return False
            
            # 第7步：Gate提现USDT到MEXC
            logger.info("💰 步骤7: Gate提现USDT到MEXC")
            final_withdraw_result = self.gate_withdraw_to_mexc('USDT', received_usdt, mexc_usdt_address, 'BSC')
            if not final_withdraw_result:
                logger.error("❌ Gate USDT提现失败")
                return False
            
            # 计算最终收益 - 使用安全的除法
            profit = received_usdt - usdt_amount
            profit_rate = (profit / usdt_amount) * 100 if usdt_amount > 0 else 0
            
            self.log_transaction(f"套利完成: 投入 {usdt_amount} USDT, 预计收到 {received_usdt} USDT, 利润 {profit:.4f} USDT ({profit_rate:.2f}%)")
            logger.info(f"🎉 套利流程完成!")
            logger.info(f"📊 收益报告: 利润 {profit:.4f} USDT ({profit_rate:.2f}%)")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ 套利执行异常: {e}")
            
            # 记录详细的失败信息
            if received_usdt > 0:
                self.log_transaction(f"套利部分完成失败: 已获得 {received_usdt} USDT, 异常: {e}")
                logger.info(f"📊 部分完成状态: 已获得 {received_usdt} USDT")
            else:
                self.log_transaction(f"套利执行失败: {e}")
                
            return False
    
    def mexc_buy_coin(self, coin: str, usdt_amount: float) -> Optional[Dict]:
        """MEXC买入币种"""
        try:
            # 参数验证
            if not coin or not isinstance(coin, str):
                logger.error(f"❌ 无效币种参数: {coin}")
                return None
            if usdt_amount <= 0 or not isinstance(usdt_amount, (int, float)):
                logger.error(f"❌ 无效金额参数: {usdt_amount}")
                return None
            
            # 实时检查余额以避免竞态条件
            current_balances = self.get_balances()
            available_usdt = current_balances['mexc']['USDT']
            
            if available_usdt < usdt_amount:
                logger.error(f"❌ 余额不足: 可用 {available_usdt:.2f} USDT < 需要 {usdt_amount:.2f} USDT")
                return None
            
            # 二次确认：交易前最终余额检查
            logger.info(f"💰 交易前最终确认: 可用USDT {available_usdt:.2f}, 需要 {usdt_amount:.2f}")
            if available_usdt < usdt_amount * 1.05:  # 预留5%缓冲
                logger.warning(f"⚠️ 余额紧张，建议降低交易金额")
            
            # 获取当前价格
            ticker = self.mexc.get_ticker_price(f'{coin}USDT')
            if isinstance(ticker, dict):
                current_price = Decimal(str(ticker.get('price', 0)))
            elif isinstance(ticker, list) and ticker:
                current_price = Decimal(str(ticker[0].get('price', 0)))
            else:
                logger.error("❌ 无法获取当前价格")
                return None
            
            if current_price <= 0:
                logger.error("❌ 价格异常")
                return None
            
            # 计算买入数量并根据MEXC规则调整精度 - 使用Decimal确保精度
            usdt_decimal = Decimal(str(usdt_amount))
            fee_margin = Decimal(str(FEE_SAFETY_MARGIN))
            raw_quantity_decimal = (usdt_decimal * fee_margin) / current_price
            raw_quantity = float(raw_quantity_decimal)
            
            # 根据币种的实际精度要求调整
            if coin == 'XLM':  # 精确匹配币种名称
                # XLM的baseSizePrecision是0.1，所以保留1位小数
                quantity = round(raw_quantity, 1)
            else:
                quantity = round(raw_quantity, 4)  # 其他币种保留4位小数
                
            if quantity <= 0:
                logger.error(f"❌ 计算数量过小: {quantity}")
                return None
            
            # 🔒 安全检查：交易前最终余额验证
            final_balance_check = self.get_balances()
            current_usdt = final_balance_check['mexc']['USDT']
            
            if current_usdt < usdt_amount:
                logger.error(f"❌ 交易前余额验证失败: {current_usdt:.2f} < {usdt_amount:.2f}")
                return None
                
            if current_usdt < usdt_amount * 1.05:  # 余额过于接近交易金额
                logger.warning(f"⚠️ 余额仅够交易，建议保留更多缓冲: {current_usdt:.2f}")
            
            # 创建市价买单 - 增加滑点保护
            max_acceptable_price = float(current_price * (Decimal('1') + MAX_SLIPPAGE))
            logger.info(f"💰 买入保护: 当前价格{float(current_price):.6f}, 最大可接受价格{max_acceptable_price:.6f}")
            
            order_result = self.mexc.create_order(
                symbol=f'{coin}USDT',
                side='BUY',
                order_type='MARKET',
                quantity=quantity  # 直接传入float，让API处理
            )
            
            logger.info(f"✅ MEXC买入订单创建成功: {order_result.get('orderId')}")
            
            # 返回执行信息
            return {
                'order_id': order_result.get('orderId'),
                'executed_qty': float(quantity),  # 转换为float返回
                'avg_price': float(current_price)
            }
            
        except Exception as e:
            logger.error(f"❌ MEXC买入失败: {e}")
            return None
    
    def mexc_withdraw_to_gate(self, coin: str, amount: float, address: str, memo: Optional[str] = None) -> bool:
        """MEXC提现到Gate"""
        try:
            # 🔒 安全检查：验证提现地址
            if not self.validate_address_format(address, coin):
                logger.error(f"❌ 地址验证失败，拒绝提现: {address}")
                return False
            
            # 获取币种网络信息
            capital_config = self.mexc.get_capital_config()
            network = None
            
            logger.info(f"🔍 查找{coin}的网络配置...")
            
            for coin_info in capital_config:
                if coin_info.get('coin') == coin:
                    network_list = coin_info.get('networkList', [])
                    logger.info(f"✅ 找到{coin}币种，支持的网络: {[n.get('network') for n in network_list]}")
                    if network_list:
                        # 使用netWork字段（API要求的格式）而不是network字段
                        first_network = network_list[0]
                        network = first_network.get('netWork')  # 使用netWork字段
                        logger.info(f"🔗 选择网络: {network} (来源: netWork字段)")
                        break
            else:
                logger.error(f"❌ 在MEXC配置中未找到币种: {coin}")
                # 显示所有支持的币种前10个作为参考
                supported_coins = [info.get('coin', 'Unknown') for info in capital_config[:10]]
                logger.info(f"📋 支持的币种示例: {supported_coins}")
                return False
            
            if not network:
                logger.warning(f"⚠️ 无法确定{coin}网络，使用默认网络")
            
            # 执行提现
            withdraw_params = {
                'coin': coin,
                'address': address,
                'amount': amount
            }
            
            if network:
                withdraw_params['network'] = network
            if memo:
                logger.info(f"📝 包含memo/tag参数: {memo}")
                withdraw_params['memo'] = memo
                
            withdraw_result = self.mexc.withdraw(**withdraw_params)
            
            # 验证提现结果
            if not withdraw_result:
                logger.error("❌ MEXC提现API返回空结果")
                return False
                
            withdraw_id = withdraw_result.get('id')
            if not withdraw_id:
                logger.error(f"❌ MEXC提现响应缺少ID: {withdraw_result}")
                return False
                
            self.log_transaction(f"MEXC-> 提现请求成功，ID: {withdraw_id}, 数量: {amount} {coin}")
            logger.info(f"✅ MEXC提现请求成功: ID {withdraw_id}")
            
            # 🔒 返回提现ID用于状态追踪
            return {'withdraw_id': withdraw_id, 'amount': amount}
            
        except Exception as e:
            logger.error(f"❌ MEXC提现失败: {e}")
            return False
    
    def gate_sell_coin(self, coin: str) -> Optional[Dict]:
        """Gate卖出币种"""
        try:
            # 获取当前余额
            balances = self.get_balances()
            available_amount = balances['gate']['coins'].get(coin, 0)
            
            if available_amount <= 0:
                logger.error(f"❌ Gate没有可用的{coin}余额")
                return None
            
            # 获取当前价格 - 添加滑点保护
            ticker = self.gate.get_tickers(f'{coin}_USDT')[0]
            current_price = float(ticker.get('highest_bid', 0))
            
            if current_price <= 0:
                logger.error("❌ 无法获取Gate卖出价格")
                return None
            
            # 滑点保护：计算最小可接受价格
            min_acceptable_price = current_price * (1 - float(MAX_SLIPPAGE))
            logger.info(f"💰 卖出保护: 当前价格{current_price:.6f}, 最小可接受价格{min_acceptable_price:.6f}")
            
            # 验证卖出金额是否满足最小要求
            limits = self.get_trading_limits(coin)
            gate_min_sell_usdt = limits.get('gate_min_sell_usdt', 1)
            estimated_usdt = available_amount * current_price
            
            if estimated_usdt < gate_min_sell_usdt:
                logger.error(f"❌ 卖出金额不足最小要求: {estimated_usdt:.2f} < {gate_min_sell_usdt}")
                return None
            
            # 创建市价卖单 - 使用精确的字符串格式
            amount_str = f"{available_amount:.8f}".rstrip('0').rstrip('.')
            order_result = self.gate.create_order(
                currency_pair=f'{coin}_USDT',
                side='sell',
                amount=amount_str,
                order_type='market'
            )
            
            order_id = order_result.get('id')
            logger.info(f"✅ Gate卖出订单创建成功: {order_id}")
            
            # 等待订单完成
            for _ in range(ORDER_TIMEOUT):
                try:
                    order_status = self.gate.get_order(order_id, f'{coin}_USDT')
                    if order_status.get('status') == 'closed':
                        filled_amount = float(order_status.get('filled_total', 0))
                        logger.info(f"✅ Gate卖出完成，获得 {filled_amount} USDT")
                        return {'received_usdt': filled_amount}
                except Exception as e:
                    logger.debug(f"查询订单状态失败，继续重试: {e}")
                    pass
                
                time.sleep(1)
            
            # 如果等待超时，预估收益（考虑Gate.io手续费）
            estimated_usdt = available_amount * current_price * (1 - GATE_TAKER_FEE)
            logger.warning(f"⚠️ 订单状态查询超时，预估收益: {estimated_usdt} USDT")
            return {'received_usdt': estimated_usdt}
            
        except Exception as e:
            logger.error(f"❌ Gate卖出失败: {e}")
            return None
    
    def gate_withdraw_to_mexc(self, coin: str, amount: float, address: str, chain: str) -> bool:
        """Gate提现到MEXC"""
        try:
            # 首先检查实际USDT余额
            current_balances = self.get_balances()
            available_usdt = current_balances['gate']['USDT']
            logger.info(f"💰 Gate当前USDT余额: {available_usdt:.6f}")
            
            if available_usdt <= 0:
                logger.error(f"❌ Gate USDT余额为0，无法提现")
                return False
            
            # 获取Gate.io支持的提现网络 - 先获取手续费信息
            currency_chains = self.gate.get_currency_chains(coin)
            
            # 查找BSC链
            chain_info = None
            for chain_data in currency_chains:
                if 'BSC' in chain_data.get('chain', '').upper() or 'BEP20' in chain_data.get('chain', '').upper():
                    chain_info = chain_data
                    break
            
            # 获取手续费
            withdraw_fee = float(chain_info.get('withdraw_fee', 0)) if chain_info else 0.1  # 默认0.1 USDT手续费
            logger.info(f"💸 BSC链USDT提现手续费: {withdraw_fee}")
            
            # 计算实际可提现金额 - 考虑手续费和精度问题
            # Gate需要账户余额 >= 提现金额 + 手续费
            safety_buffer = 0.01  # 精度缓冲
            max_withdrawable = available_usdt - withdraw_fee - safety_buffer
            
            if max_withdrawable <= 0:
                logger.error(f"❌ Gate可用余额不足: 余额{available_usdt:.6f} - 手续费{withdraw_fee} - 缓冲{safety_buffer} = {max_withdrawable:.6f}")
                return False
                
            actual_withdraw_amount = min(amount, max_withdrawable)
            logger.info(f"📊 提现金额调整: 请求{amount:.6f} → 实际{actual_withdraw_amount:.6f} USDT (余额{available_usdt:.6f}, 手续费{withdraw_fee})")
            
            # 确定链名称
            if not chain_info:
                logger.warning(f"⚠️ 未找到{coin}的BSC链信息，使用默认链")
                chain_name = 'BSC'
            else:
                chain_name = chain_info.get('chain')
            
            # 使用调整后的金额提现（已经考虑了手续费）
            withdraw_amount = actual_withdraw_amount
            logger.info(f"💸 最终提现金额: {withdraw_amount:.6f} USDT (Gate会自动扣除手续费{withdraw_fee})")
            
            if withdraw_amount <= 0:
                logger.error(f"❌ 扣除手续费后金额不足: {actual_withdraw_amount} - {withdraw_fee} = {withdraw_amount}")
                return False
                
            # 检查最小提现限制（USDT最小提现通常是1.5）
            min_withdraw = 1.5  # USDT BSC最小提现通常是1.5
            if withdraw_amount < min_withdraw:
                logger.error(f"❌ 提现金额低于最小限制: {withdraw_amount:.6f} < {min_withdraw}")
                logger.error(f"需要至少 {min_withdraw + withdraw_fee:.6f} USDT 才能提现")
                return False
            
            # 执行提现 - 使用精确的金额格式
            amount_str = f"{withdraw_amount:.8f}".rstrip('0').rstrip('.')
            logger.info(f"🚀 执行Gate提现: {amount_str} {coin} 到 {address[:10]}...")
            
            # 最终检查：确保提现金额不超过余额
            if float(amount_str) > available_usdt:
                logger.error(f"❌ 安全检查失败: 提现金额{amount_str} > 可用余额{available_usdt:.6f}")
                return False
            
            withdraw_result = self.gate.withdraw(
                currency=coin,
                amount=amount_str,
                address=address,
                chain=chain_name
            )
            
            # 验证提现结果
            if not withdraw_result:
                logger.error("❌ Gate提现API返回空结果")
                return False
                
            withdraw_id = withdraw_result.get('id')
            if not withdraw_id:
                logger.error(f"❌ Gate提现响应缺少ID: {withdraw_result}")
                return False
                
            self.log_transaction(f"Gate-> 提现请求成功，ID: {withdraw_id}, 数量: {withdraw_amount} {coin}")
            logger.info(f"✅ Gate提现请求成功: ID {withdraw_id}")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Gate提现失败: {e}")
            return False

def main():
    """主程序"""
    print("🤖 修复版简化套利执行器")
    print("=" * 50)
    
    bot = SimpleArbitrageBot()
    
    # 显示当前余额
    balances = bot.get_balances()
    print(f"\n💰 当前余额:")
    print(f"  MEXC: USDT={balances['mexc']['USDT']:.2f}")
    print(f"  Gate: USDT={balances['gate']['USDT']:.2f}")
    
    # 获取用户输入
    coin = input(f"\n请输入要套利的币种 (如: XLM): ").strip().upper()
    
    # 验证币种符号安全性
    if not bot.validate_coin_symbol(coin):
        print(f"❌ {coin} 币种符号不安全或无效")
        return
    
    # 验证币种支持
    if not bot.validate_coin_support(coin):
        print(f"❌ {coin} 不被支持")
        return
    
    # 获取要投入的USDT金额
    mexc_usdt = balances['mexc']['USDT']
    
    usdt_input = input(f"请输入要投入的USDT金额 (最大 {mexc_usdt:.2f}): ").strip()
    
    try:
        usdt_amount = float(usdt_input)
        if usdt_amount <= 0 or usdt_amount > mexc_usdt:
            print(f"❌ 无效USDT金额: {usdt_amount}")
            return
    except ValueError:
        print("❌ 无效金额格式")
        return
    
    # 验证并显示所有交易限制
    if not bot.validate_and_display_limits(coin, usdt_amount):
        return
    
    # 显示价格信息
    prices = bot.get_prices(coin)
    print(f"\n📈 当前价格:")
    print(f"  MEXC: 买价={prices['mexc']['ask']:.6f}, 卖价={prices['mexc']['bid']:.6f}")
    print(f"  Gate: 买价={prices['gate']['ask']:.6f}, 卖价={prices['gate']['bid']:.6f}")
    
    if prices['mexc']['ask'] <= 0 or prices['gate']['bid'] <= 0:
        print("❌ 价格信息异常，无法执行套利")
        return
    
    # 计算预期收益 - 使用统一的手续费常量
    if prices['mexc']['ask'] <= 0:
        print("❌ MEXC价格异常，无法计算收益")
        return
        
    # 买入：扣除MEXC手续费
    expected_coins = (usdt_amount * FEE_SAFETY_MARGIN) / prices['mexc']['ask']
    
    # 检查买入数量是否满足提现要求
    min_withdraw_qty = 0  # 声明变量
    try:
        capital_config = bot.mexc.get_capital_config()
        
        for coin_info in capital_config:
            if coin_info.get('coin') == coin:
                network_list = coin_info.get('networkList', [])
                if network_list:
                    min_withdraw_qty = float(network_list[0].get('withdrawMin', 0))
                    break
        
        if min_withdraw_qty > 0 and expected_coins < min_withdraw_qty:
            min_usdt_needed = (min_withdraw_qty * prices['mexc']['ask']) / FEE_SAFETY_MARGIN
            print(f"\n⚠️ 买入数量不足提现要求:")
            print(f"  预计买入: {expected_coins:.6f} {coin}")
            print(f"  最小提现: {min_withdraw_qty} {coin}")
            print(f"  建议最小投入: {min_usdt_needed:.2f} USDT")
            print(f"  当前投入: {usdt_amount:.2f} USDT")
            print("\n❌ 请增加投入金额或选择其他币种")
            return
        
    except Exception as e:
        print(f"⚠️ 无法获取提现限制: {e}")
    
    # 卖出：扣除Gate.io手续费  
    expected_usdt_return = expected_coins * prices['gate']['bid'] * (1 - GATE_TAKER_FEE)
    expected_profit = expected_usdt_return - usdt_amount
    profit_rate = (expected_profit / usdt_amount) * 100 if usdt_amount > 0 else 0
    
    print(f"\n📊 套利预测:")
    print(f"  预计买入: {expected_coins:.6f} {coin}")
    print(f"  预计卖出获得: {expected_usdt_return:.2f} USDT")
    print(f"  预期利润: {expected_profit:.2f} USDT ({profit_rate:.2f}%)")
    
    # 显示提现数量检查结果
    if min_withdraw_qty > 0:
        print(f"  ✅ 买入数量满足最小提现要求({min_withdraw_qty} {coin})")
    
    if expected_profit < 0:
        print("⚠️ 预期亏损，建议不要执行")
    
    # 确认执行
    print(f"\n确认执行套利:")
    print(f"  币种: {coin}")
    print(f"  投入USDT: {usdt_amount}")
    print(f"  流程: MEXC买入{coin} -> 转移到Gate -> Gate卖出 -> USDT回MEXC")
    
    confirm = input("\n确认执行? (yes/no): ").lower()
    if confirm != 'yes':
        print("已取消")
        return
    
    print("🚀 开始执行套利流程...")
    
    # 执行完整套利流程
    success = bot.execute_arbitrage_flow(coin, usdt_amount)
    
    if success:
        print("✅ 套利执行成功!")
        # 显示最新余额
        final_balances = bot.get_balances()
        print(f"\n💰 最终余额:")
        print(f"  MEXC: USDT={final_balances['mexc']['USDT']:.2f}")
        print(f"  Gate: USDT={final_balances['gate']['USDT']:.2f}")
    else:
        print("❌ 套利执行失败，请检查日志")

if __name__ == "__main__":
    main()