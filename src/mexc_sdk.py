"""
MEXC交易所SDK
实现MEXC API的认证和交易接口
"""
import hashlib
import hmac
import time
import json
import requests
from typing import Dict, Any, Optional, List
from urllib.parse import urlencode
import logging

class MEXCSDK:
    def __init__(self, api_key: str, secret_key: str, base_url: str = None):
        """
        初始化MEXC SDK
        
        Args:
            api_key: API密钥
            secret_key: 密钥
            base_url: API基础URL
        """
        self.api_key = api_key
        self.secret_key = secret_key
        self.base_url = base_url or "https://api.mexc.com"
        self.session = requests.Session()
        
        self.logger = logging.getLogger('MEXCSDK')
        
    def _generate_signature(self, query_string: str) -> str:
        """生成签名 - MEXC要求小写"""
        return hmac.new(
            self.secret_key.encode('utf-8'),
            query_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest().lower()  # MEXC使用标准大小写
    
    def _build_signed_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """构建带签名的参数"""
        # 添加时间戳
        params['timestamp'] = int(time.time() * 1000)
        params['recvWindow'] = 5000
        
        # MEXC签名：按字母顺序排序参数
        sorted_params = {}
        for key in sorted(params.keys()):
            sorted_params[key] = params[key]
        
        # 构建查询字符串
        query_string = urlencode(sorted_params, doseq=True)
        
        self.logger.debug(f"签名前查询字符串: {query_string}")
        
        # 生成签名
        signature = self._generate_signature(query_string)
        sorted_params['signature'] = signature
        
        self.logger.debug(f"生成签名: {signature}")
        
        return sorted_params
    
    def _request(self, method: str, endpoint: str, params: Dict[str, Any] = None,
                signed: bool = True) -> Dict[str, Any]:
        """发送HTTP请求"""
        if params is None:
            params = {}
        
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        
        if signed:
            params = self._build_signed_params(params)
        
        self.logger.debug(f"请求 {method} {url}")
        self.logger.debug(f"参数: {params}")
        
        try:
            if method.upper() == 'GET':
                headers = {
                    'X-MEXC-APIKEY': self.api_key
                }
                response = self.session.get(url, params=params, headers=headers, timeout=10)
            elif method.upper() == 'DELETE':
                headers = {
                    'X-MEXC-APIKEY': self.api_key
                }
                response = self.session.delete(url, params=params, headers=headers, timeout=10)
            else:
                # POST请求 - 根据MEXC文档，所有参数都在query string中发送
                headers = {
                    'X-MEXC-APIKEY': self.api_key
                }
                if params:
                    response = self.session.post(url, params=params, headers=headers, timeout=10)
                else:
                    response = self.session.post(url, headers=headers, timeout=10)
            
            # 先获取响应内容
            try:
                result = response.json()
            except (ValueError, requests.exceptions.JSONDecodeError):
                result = response.text
            
            # 检查HTTP状态码
            if response.status_code != 200:
                self.logger.error(f"API错误 {response.status_code}: {result}")
                error_msg = result.get('msg', str(result)) if isinstance(result, dict) else str(result)
                raise Exception(f"MEXC API错误: {error_msg}")
            
            self.logger.debug(f"API响应: {result}")
            return result
            
        except requests.exceptions.RequestException as e:
            self.logger.error(f"请求异常: {e}")
            raise Exception(f"MEXC API请求失败: {e}")
    
    # 公共接口
    def ping(self) -> bool:
        """测试连接"""
        try:
            result = self._request('GET', '/api/v3/ping', signed=False)
            return True
        except (requests.exceptions.RequestException, Exception):
            return False
    
    def get_server_time(self) -> int:
        """获取服务器时间"""
        result = self._request('GET', '/api/v3/time', signed=False)
        return result['serverTime']
    
    def get_exchange_info(self) -> Dict[str, Any]:
        """获取交易规则和交易对信息"""
        return self._request('GET', '/api/v3/exchangeInfo', signed=False)
    
    def format_quantity(self, symbol: str, quantity: float) -> str:
        """
        根据交易对规则格式化数量精度
        
        Args:
            symbol: 交易对，如 'XLMUSDT'
            quantity: 原始数量
            
        Returns:
            格式化后的数量字符串
        """
        # 先确保quantity是数值类型
        try:
            qty_float = float(quantity)
        except (ValueError, TypeError):
            self.logger.error(f"无效数量类型: {quantity}")
            return "1.0"
        
        try:
            # 获取交易规则
            exchange_info = self.get_exchange_info()
            
            for symbol_info in exchange_info.get('symbols', []):
                if symbol_info.get('symbol') == symbol:
                    # 查找LOT_SIZE过滤器
                    for filter_info in symbol_info.get('filters', []):
                        if filter_info.get('filterType') == 'LOT_SIZE':
                            step_size = float(filter_info.get('stepSize', '1'))
                            min_qty = float(filter_info.get('minQty', '0'))
                            
                            # 计算精度位数
                            step_str = filter_info.get('stepSize', '1')
                            if '.' in step_str:
                                precision = len(step_str.split('.')[1].rstrip('0'))
                            else:
                                precision = 0
                            
                            # 确保数量不低于最小值
                            qty_float = max(qty_float, min_qty)
                            
                            # 调整到stepSize的倍数
                            qty_float = round(qty_float / step_size) * step_size
                            
                            # 格式化到正确精度
                            result = f"{qty_float:.{precision}f}"
                            return result.rstrip('0').rstrip('.') if precision > 0 else result
            
            # 如果没找到规则，使用默认精度
            return f"{qty_float:.4f}".rstrip('0').rstrip('.')
            
        except Exception as e:
            self.logger.warning(f"API获取交易规则失败，使用币种默认精度: {e}")
            
            # 使用一些常见币种的默认精度 - 但保持原始数量
            common_precisions = {
                'BTC': 6, 'ETH': 5, 'XLM': 1, 'DOGE': 0, 'TRX': 0, 
                'ADA': 1, 'LTC': 5, 'DOT': 3, 'UNI': 3
            }
            base = symbol.replace('USDT', '').replace('BTC', '').replace('ETH', '')
            precision = common_precisions.get(base, 4)
            
            # 格式化到指定精度，但保持原始数量值
            result = f"{qty_float:.{precision}f}"
            return result.rstrip('0').rstrip('.') if precision > 0 else result
    
    def get_ticker_24hr(self, symbol: str = None) -> List[Dict[str, Any]]:
        """获取24小时价格变动情况"""
        params = {}
        if symbol:
            params['symbol'] = symbol
        return self._request('GET', '/api/v3/ticker/24hr', params, signed=False)
    
    def get_ticker_price(self, symbol: str = None) -> List[Dict[str, Any]]:
        """获取最新价格"""
        params = {}
        if symbol:
            params['symbol'] = symbol
        return self._request('GET', '/api/v3/ticker/price', params, signed=False)
    
    def get_order_book(self, symbol: str, limit: int = 100) -> Dict[str, Any]:
        """获取订单薄"""
        params = {
            'symbol': symbol,
            'limit': limit
        }
        return self._request('GET', '/api/v3/depth', params, signed=False)
    
    # 私有接口
    def get_account_info(self) -> Dict[str, Any]:
        """获取账户信息"""
        return self._request('GET', '/api/v3/account')
    
    def get_balances(self) -> List[Dict[str, Any]]:
        """获取余额信息"""
        account = self.get_account_info()
        return account.get('balances', [])
    
    def create_order(self, symbol: str, side: str, order_type: str, 
                    quantity: Optional[float] = None, price: Optional[float] = None,
                    time_in_force: str = 'GTC') -> Dict[str, Any]:
        """
        创建订单
        
        Args:
            symbol: 交易对，如 'DOGEUSDT'
            side: 买卖方向 'BUY' 或 'SELL'
            order_type: 订单类型 'LIMIT', 'MARKET'
            quantity: 数量
            price: 价格(限价单必需)
            time_in_force: 时间有效性 'GTC', 'IOC', 'FOK'
        """
        params = {
            'symbol': symbol,
            'side': side,
            'type': order_type,
        }
        
        # 市价单不需要timeInForce
        if order_type != 'MARKET':
            params['timeInForce'] = time_in_force
        
        if quantity is not None:
            # 根据MEXC官方API规则处理数量精度
            if symbol == 'XLMUSDT':  # 精确匹配，避免误匹配其他交易对
                # XLM的baseSizePrecision是0.1，保留1位小数
                params['quantity'] = f"{float(quantity):.1f}"
            else:
                params['quantity'] = str(quantity)
        if price is not None:
            params['price'] = str(price)
        
        self.logger.info(f"创建订单参数（签名前）: {params}")
        
        return self._request('POST', '/api/v3/order', params)
    
    def cancel_order(self, symbol: str, order_id: int = None, 
                    orig_client_order_id: str = None) -> Dict[str, Any]:
        """取消订单"""
        params = {'symbol': symbol}
        
        if order_id:
            params['orderId'] = order_id
        if orig_client_order_id:
            params['origClientOrderId'] = orig_client_order_id
        
        return self._request('DELETE', '/api/v3/order', params)
    
    def get_order(self, symbol: str, order_id: int = None,
                 orig_client_order_id: str = None) -> Dict[str, Any]:
        """查询订单"""
        params = {'symbol': symbol}
        
        if order_id:
            params['orderId'] = order_id
        if orig_client_order_id:
            params['origClientOrderId'] = orig_client_order_id
        
        return self._request('GET', '/api/v3/order', params)
    
    def get_open_orders(self, symbol: str = None) -> List[Dict[str, Any]]:
        """查询当前挂单"""
        params = {}
        if symbol:
            params['symbol'] = symbol
        
        return self._request('GET', '/api/v3/openOrders', params)
    
    def get_deposit_address(self, coin: str, network: str = None) -> Dict[str, Any]:
        """获取充值地址"""
        params = {'coin': coin}
        if network:
            params['network'] = network
        
        return self._request('GET', '/api/v3/capital/deposit/address', params)
    
    def withdraw(self, coin: str, address: str, amount: float, 
                network: str = None, memo: str = None, 
                withdrawOrderId: str = None, contractAddress: str = None,
                remark: str = None) -> Dict[str, Any]:
        """提现（新接口）
        
        根据MEXC官方最新文档：
        POST /api/v3/capital/withdraw
        
        Args:
            coin: 币种（必需）
            address: 提现地址（必需）  
            amount: 提现数量（必需）
            network: 提现网络（可选）
            memo: 地址备注/标签（可选，XLM/XRP等币种必需）
            withdrawOrderId: 自定义提币ID（可选）
            contractAddress: 币种智能合约地址（可选）
            remark: 备注（可选）
        
        Returns:
            Dict containing withdrawal ID
        """
        params = {
            'coin': coin,
            'address': address,
            'amount': str(amount)
        }
        
        # 添加可选参数
        if network:
            params['netWork'] = network  # 使用文档中的正确参数名
        if memo:
            params['memo'] = memo
        if withdrawOrderId:
            params['withdrawOrderId'] = withdrawOrderId
        if contractAddress:
            params['contractAddress'] = contractAddress
        if remark:
            params['remark'] = remark
        
        # 使用新的API端点
        return self._request('POST', '/api/v3/capital/withdraw', params)
    
    def get_deposit_history(self, coin: str = None, status: int = None,
                           start_time: int = None, end_time: int = None,
                           offset: int = 0, limit: int = 1000) -> List[Dict[str, Any]]:
        """查询充值历史"""
        params = {
            'offset': offset,
            'limit': limit
        }
        
        if coin:
            params['coin'] = coin
        if status is not None:
            params['status'] = status
        if start_time:
            params['startTime'] = start_time
        if end_time:
            params['endTime'] = end_time
        
        return self._request('GET', '/api/v3/capital/deposit/hisrec', params)
    
    def get_withdraw_history(self, coin: str = None, status: int = None,
                           start_time: int = None, end_time: int = None,
                           offset: int = 0, limit: int = 1000) -> List[Dict[str, Any]]:
        """查询提现历史"""
        params = {
            'offset': offset,
            'limit': limit
        }
        
        if coin:
            params['coin'] = coin
        if status is not None:
            params['status'] = status
        if start_time:
            params['startTime'] = start_time
        if end_time:
            params['endTime'] = end_time
        
        return self._request('GET', '/api/v3/capital/withdraw/history', params)
    
    def get_trading_fees(self, symbol: str = None) -> List[Dict[str, Any]]:
        """查询交易手续费率"""
        params = {}
        if symbol:
            params['symbol'] = symbol
        
        return self._request('GET', '/api/v3/tradeFee', params)
    
    def get_capital_config(self) -> List[Dict[str, Any]]:
        """查询币种信息 - 包含提现限制"""
        return self._request('GET', '/api/v3/capital/config/getall')