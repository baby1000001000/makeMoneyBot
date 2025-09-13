"""
Gate.io 交易所SDK
实现Gate.io API v4的认证和交易接口
"""
import hashlib
import hmac
import time
import json
import requests
from typing import Dict, Any, Optional, List
from urllib.parse import urlencode
import logging

class GateSDK:
    def __init__(self, api_key: str, secret_key: str, proxy: Optional[str] = None):
        """
        初始化Gate.io SDK
        
        Args:
            api_key: API密钥
            secret_key: 私钥
            proxy: 代理地址，格式如 "http://127.0.0.1:7890"
        """
        self.api_key = api_key
        self.secret_key = secret_key
        self.base_url = "https://api.gateio.ws/api/v4"
        self.session = requests.Session()
        
        # 设置代理
        if proxy:
            self.session.proxies = {
                'http': proxy,
                'https': proxy
            }
            self.logger = logging.getLogger('GateSDK')
            self.logger.info(f"已设置代理: {proxy}")
        else:
            self.logger = logging.getLogger('GateSDK')
    
    def _generate_signature(self, method: str, url_path: str, query_string: str = "",
                          body: str = "", timestamp: str = "") -> str:
        """
        生成Gate.io API v4签名 - 完全按照官方例子实现
        """
        # 完全按照官方例子的实现方式
        m = hashlib.sha512()
        m.update((body or "").encode('utf-8'))
        hashed_payload = m.hexdigest()
        
        # 使用官方例子的格式字符串构建方式
        s = '%s\n%s\n%s\n%s\n%s' % (method, url_path, query_string or "", hashed_payload, timestamp)
        
        # 使用HMAC-SHA512生成签名
        sign = hmac.new(self.secret_key.encode('utf-8'), s.encode('utf-8'), hashlib.sha512).hexdigest()
        
        return sign
    
    def _build_headers(self, method: str, url_path: str, query_string: str = "",
                      body: str = "") -> Dict[str, str]:
        """构建请求头 - 完全按照Gate.io官方例子实现"""
        # 完全按照官方例子的时间戳生成方式
        t = time.time()
        timestamp = str(t)
        signature = self._generate_signature(method, url_path, query_string, body, timestamp)
        
        headers = {
            'Accept': 'application/json',
            'Content-Type': 'application/json',
            'KEY': self.api_key,
            'Timestamp': timestamp,
            'SIGN': signature
        }
        
        return headers
    
    def _request(self, method: str, endpoint: str, params: Dict[str, Any] = None,
                body: Dict[str, Any] = None, signed: bool = True) -> Dict[str, Any]:
        """发送HTTP请求"""
        url_path = endpoint
        if not url_path.startswith('/'):
            url_path = '/' + url_path
        
        url = self.base_url + url_path
        query_string = ""
        request_body = ""
        
        # 处理查询参数
        if params:
            query_string = urlencode(sorted(params.items()))
            
        # 处理请求体
        if body:
            request_body = json.dumps(body, separators=(',', ':'))
        
        # 构建请求头
        if signed:
            # 签名需要使用完整的API路径，包含/api/v4前缀
            full_url_path = url_path
            if not full_url_path.startswith('/api/v4'):
                full_url_path = '/api/v4' + url_path
            headers = self._build_headers(method, full_url_path, query_string, request_body)
        else:
            headers = {
                'Accept': 'application/json',
                'Content-Type': 'application/json'
            }
        
        try:
            self.logger.debug(f"请求 {method} {url}, 参数: {params}, 请求体: {body}")
            
            if method.upper() == 'GET':
                response = self.session.get(url, params=params, headers=headers, timeout=10)
            elif method.upper() == 'POST':
                response = self.session.post(
                    url, params=params, data=request_body, headers=headers, timeout=10
                )
            elif method.upper() == 'DELETE':
                response = self.session.delete(
                    url, params=params, data=request_body, headers=headers, timeout=10
                )
            else:
                raise ValueError(f"不支持的HTTP方法: {method}")
            
            response.raise_for_status()
            
            # 处理空响应
            if not response.text:
                return {}
                
            return response.json()
            
        except requests.exceptions.RequestException as e:
            # 尝试获取错误详情
            error_detail = None
            try:
                if hasattr(e, 'response') and e.response is not None:
                    error_detail = e.response.json()
                    self.logger.error(f"Gate.io API错误: {error_detail}")
            except (ValueError, requests.exceptions.JSONDecodeError):
                pass
            
            if error_detail:
                raise Exception(f"Gate.io API错误: {error_detail}")
            else:
                self.logger.error(f"请求异常: {e}")
                raise Exception(f"Gate.io API请求失败: {e}")
        except json.JSONDecodeError as e:
            self.logger.error(f"JSON解析失败: {e}, 响应内容: {response.text}")
            raise Exception(f"响应解析失败: {e}")
    
    # 公共接口
    def get_currencies(self) -> List[Dict[str, Any]]:
        """获取所有支持的币种信息"""
        return self._request('GET', '/wallet/currencies', signed=True)
    
    def get_currency_pairs(self, currency_pair: Optional[str] = None) -> List[Dict[str, Any]]:
        """获取交易对信息"""
        endpoint = "/spot/currency_pairs"
        if currency_pair:
            endpoint = f"/spot/currency_pairs/{currency_pair}"
            return self._request('GET', endpoint, signed=False)
        else:
            return self._request('GET', endpoint, signed=False)
    
    def get_tickers(self, currency_pair: Optional[str] = None) -> List[Dict[str, Any]]:
        """获取ticker信息"""
        params = {}
        if currency_pair:
            params['currency_pair'] = currency_pair
        
        return self._request('GET', '/spot/tickers', params, signed=False)
    
    def get_currency_chains(self, currency: str) -> List[Dict[str, Any]]:
        """查询币种支持的链"""
        params = {'currency': currency}
        return self._request('GET', '/wallet/currency_chains', params, signed=False)
    
    # 钱包接口
    def get_deposit_address(self, currency: str) -> Dict[str, Any]:
        """获取充值地址"""
        params = {'currency': currency}
        return self._request('GET', '/wallet/deposit_address', params)
    
    def get_deposits(self, currency: Optional[str] = None, 
                    from_timestamp: Optional[int] = None,
                    to_timestamp: Optional[int] = None,
                    limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """获取充值记录"""
        params = {}
        if currency:
            params['currency'] = currency
        if from_timestamp:
            params['from'] = from_timestamp
        if to_timestamp:
            params['to'] = to_timestamp
        if limit:
            params['limit'] = limit
            
        return self._request('GET', '/wallet/deposits', params)
    
    def get_withdrawals(self, currency: Optional[str] = None,
                       from_timestamp: Optional[int] = None,
                       to_timestamp: Optional[int] = None,
                       limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """获取提现记录"""
        params = {}
        if currency:
            params['currency'] = currency
        if from_timestamp:
            params['from'] = from_timestamp
        if to_timestamp:
            params['to'] = to_timestamp
        if limit:
            params['limit'] = limit
            
        return self._request('GET', '/wallet/withdrawals', params)
    
    def get_deposit_address(self, currency: str, chain: Optional[str] = None) -> Dict[str, Any]:
        """
        获取充值地址
        
        Args:
            currency: 币种，如 'DOGE'
            chain: 链名称，如 'DOGE', 'ETH', 'TRX' 等
        """
        params = {'currency': currency}
        if chain:
            params['chain'] = chain
        
        try:
            addresses = self._request('GET', '/wallet/deposit_address', params)
            # 返回第一个地址
            if addresses and isinstance(addresses, list) and len(addresses) > 0:
                return addresses[0]
            return addresses
        except Exception as e:
            self.logger.error(f"获取充值地址失败: {e}")
            return None
    
    def generate_deposit_address(self, currency: str, chain: Optional[str] = None) -> Dict[str, Any]:
        """
        生成新的充值地址
        
        Args:
            currency: 币种
            chain: 链名称
        """
        body = {'currency': currency}
        if chain:
            body['chain'] = chain
            
        try:
            return self._request('POST', '/wallet/deposit_address', body=body)
        except Exception as e:
            self.logger.error(f"生成充值地址失败: {e}")
            return None
    
    # 现货交易接口
    def get_account(self) -> Dict[str, Any]:
        """获取现货账户信息"""
        return self._request('GET', '/spot/accounts')
    
    def get_spot_accounts(self) -> List[Dict[str, Any]]:
        """获取现货账户余额列表"""
        return self._request('GET', '/spot/accounts')
    
    def get_wallet_balance(self) -> Dict[str, Any]:
        """获取钱包总余额"""
        return self._request('GET', '/wallet/total_balance')
    
    def check_api_permissions(self) -> Dict[str, bool]:
        """检查API权限"""
        permissions = {
            'public_api': False,
            'spot_trading': False,
            'wallet': False,
            'withdraw': False
        }
        
        try:
            # 测试公开API
            self.get_tickers('BTC_USDT')
            permissions['public_api'] = True
        except (Exception,):
            pass
        
        try:
            # 测试现货交易权限
            self.get_spot_accounts()
            permissions['spot_trading'] = True
        except (Exception,):
            pass
            
        try:
            # 测试钱包权限
            self.get_wallet_balance()
            permissions['wallet'] = True
        except (Exception,):
            pass
            
        try:
            # 测试提现权限（查看提现记录）
            self.get_withdrawals(limit=1)
            permissions['withdraw'] = True
        except (Exception,):
            pass
            
        return permissions
    
    def create_order(self, currency_pair: str, side: str, amount: str,
                    price: Optional[str] = None, order_type: str = "limit",
                    time_in_force: str = "gtc", iceberg: str = "0",
                    auto_borrow: bool = False, auto_repay: bool = False,
                    text: Optional[str] = None) -> Dict[str, Any]:
        """
        创建现货订单
        
        Args:
            currency_pair: 交易对，如 'BTC_USDT'
            side: 买卖方向 'buy' 或 'sell'
            amount: 交易数量
            price: 价格(限价单必需)
            order_type: 订单类型 'limit' 或 'market'
            time_in_force: 时间策略 'gtc', 'ioc', 'poc', 'fok'
            iceberg: 冰山委托数量，0表示普通订单
            auto_borrow: 是否自动借币
            auto_repay: 是否自动还款
            text: 自定义订单标识
        """
        body = {
            'currency_pair': currency_pair,
            'side': side,
            'amount': amount,
            'type': order_type,
            'iceberg': iceberg,
            'auto_borrow': auto_borrow,
            'auto_repay': auto_repay
        }
        
        # 市价订单仅支持ioc和fok，限价订单支持所有类型
        if order_type == 'market':
            # 市价订单默认使用ioc (立即成交或取消)
            if time_in_force not in ['ioc', 'fok']:
                body['time_in_force'] = 'ioc'
            else:
                body['time_in_force'] = time_in_force
        else:
            # 限价订单支持所有time_in_force选项
            body['time_in_force'] = time_in_force
        
        if price:
            body['price'] = price
        if text:
            body['text'] = text
            
        return self._request('POST', '/spot/orders', body=body)
    
    def get_orders(self, currency_pair: str, status: str = "open",
                  page: int = 1, limit: int = 100) -> List[Dict[str, Any]]:
        """查询订单列表"""
        params = {
            'currency_pair': currency_pair,
            'status': status,
            'page': page,
            'limit': limit
        }
        
        return self._request('GET', '/spot/orders', params)
    
    def get_order(self, order_id: str, currency_pair: str) -> Dict[str, Any]:
        """查询单个订单"""
        params = {'currency_pair': currency_pair}
        return self._request('GET', f'/spot/orders/{order_id}', params)
    
    def cancel_order(self, order_id: str, currency_pair: str) -> Dict[str, Any]:
        """取消订单"""
        params = {'currency_pair': currency_pair}
        return self._request('DELETE', f'/spot/orders/{order_id}', params)
    
    def cancel_all_orders(self, currency_pair: str, side: Optional[str] = None) -> List[Dict[str, Any]]:
        """批量取消订单"""
        body = {'currency_pair': currency_pair}
        if side:
            body['side'] = side
            
        return self._request('DELETE', '/spot/orders', body=body)
    
    def get_trades(self, currency_pair: str, limit: int = 100,
                  page: int = 1, order_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """查询个人交易记录"""
        params = {
            'currency_pair': currency_pair,
            'limit': limit,
            'page': page
        }
        
        if order_id:
            params['order_id'] = order_id
            
        return self._request('GET', '/spot/my_trades', params)
    
    def withdraw(self, currency: str, amount: str, address: str, 
                chain: Optional[str] = None, memo: Optional[str] = None) -> Dict[str, Any]:
        """
        提现到外部地址
        
        Args:
            currency: 币种
            amount: 提现数量
            address: 提现地址
            chain: 链类型 (如 'TRC20', 'BSC', 'ETH' 等)
            memo: 备注信息 (某些币种需要)
        """
        body = {
            'currency': currency,
            'amount': amount,
            'address': address
        }
        
        if chain:
            body['chain'] = chain
        if memo:
            body['memo'] = memo
            
        return self._request('POST', '/withdrawals', body=body)