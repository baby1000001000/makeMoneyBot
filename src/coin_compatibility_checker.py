#!/usr/bin/env python3
"""
币种兼容性检查器
验证MEXC和Gate.io之间币种的完全兼容性
"""
import time
from typing import Dict, List, Tuple, Optional
import logging

class CoinCompatibilityChecker:
    """币种兼容性检查器"""
    
    def __init__(self, mexc_sdk, gate_sdk):
        self.mexc_sdk = mexc_sdk
        self.gate_sdk = gate_sdk
        self.logger = logging.getLogger('CoinChecker')
        
    def check_coin_full_compatibility(self, symbol: str) -> Dict[str, any]:
        """
        全面检查币种兼容性
        
        Args:
            symbol: 交易对符号，如 'BTC/USDT'
            
        Returns:
            Dict: 完整的兼容性报告
        """
        base, quote = symbol.split('/')
        
        report = {
            'symbol': symbol,
            'base_currency': base,
            'quote_currency': quote,
            'mexc_trading': False,
            'gate_trading': False,
            'mexc_deposit': False,
            'mexc_withdraw': False,
            'gate_deposit': False,
            'gate_withdraw': False,
            'mexc_networks': [],
            'gate_networks': [],
            'common_networks': [],
            'compatible': False,
            'risk_level': 'HIGH',
            'issues': [],
            'recommendations': []
        }
        
        try:
            # 1. 检查MEXC交易支持
            report['mexc_trading'] = self._check_mexc_trading(symbol)
            
            # 2. 检查Gate.io交易支持
            report['gate_trading'] = self._check_gate_trading(symbol)
            
            # 3. 检查MEXC充提现支持
            mexc_deposit_info = self._check_mexc_deposit_withdraw(base)
            report['mexc_deposit'] = mexc_deposit_info['deposit_supported']
            report['mexc_withdraw'] = mexc_deposit_info['withdraw_supported']
            report['mexc_networks'] = mexc_deposit_info['networks']
            
            # 4. 检查Gate.io充提现支持
            gate_deposit_info = self._check_gate_deposit_withdraw(base)
            report['gate_deposit'] = gate_deposit_info['deposit_supported']
            report['gate_withdraw'] = gate_deposit_info['withdraw_supported']
            report['gate_networks'] = gate_deposit_info['networks']
            
            # 5. 分析网络兼容性
            report['common_networks'] = self._find_common_networks(
                report['mexc_networks'], 
                report['gate_networks']
            )
            
            # 6. 综合评估兼容性
            compatibility_result = self._evaluate_compatibility(report)
            report.update(compatibility_result)
            
        except Exception as e:
            self.logger.error(f"检查{symbol}兼容性失败: {e}")
            report['issues'].append(f"检查过程出错: {str(e)[:50]}")
            
        return report
    
    def _check_mexc_trading(self, symbol: str) -> bool:
        """检查MEXC交易支持"""
        try:
            # 获取ticker验证交易对是否存在且活跃
            ticker = self.mexc_sdk.get_ticker_price(symbol.replace('/', ''))
            return bool(ticker and ticker.get('price'))
        except Exception:
            return False
    
    def _check_gate_trading(self, symbol: str) -> bool:
        """检查Gate.io交易支持"""
        try:
            gate_symbol = symbol.replace('/', '_')
            tickers = self.gate_sdk.get_tickers(gate_symbol)
            return bool(tickers and len(tickers) > 0)
        except Exception:
            return False
    
    def _check_mexc_deposit_withdraw(self, coin: str) -> Dict[str, any]:
        """检查MEXC充提现支持"""
        result = {
            'deposit_supported': False,
            'withdraw_supported': False,
            'networks': []
        }
        
        try:
            # 获取充值地址信息
            deposit_info = self.mexc_sdk.get_deposit_address(coin=coin)
            
            if isinstance(deposit_info, list) and len(deposit_info) > 0:
                result['deposit_supported'] = True
                for addr_info in deposit_info:
                    network = addr_info.get('network', addr_info.get('coin', coin))
                    if network:
                        result['networks'].append({
                            'network': network,
                            'address': addr_info.get('address', ''),
                            'memo_required': bool(addr_info.get('tag') or addr_info.get('memo'))
                        })
                        
            elif isinstance(deposit_info, dict) and deposit_info.get('address'):
                result['deposit_supported'] = True
                result['networks'].append({
                    'network': coin,
                    'address': deposit_info.get('address', ''),
                    'memo_required': bool(deposit_info.get('tag') or deposit_info.get('memo'))
                })
            
            # 假设有充值地址就支持提现（实际应该有专门的提现检查API）
            result['withdraw_supported'] = result['deposit_supported']
            
        except Exception as e:
            if 'not exist' in str(e).lower():
                result['networks'] = []
            else:
                # 可能是网络问题，标记为未知
                pass
                
        return result
    
    def _check_gate_deposit_withdraw(self, coin: str) -> Dict[str, any]:
        """检查Gate.io充提现支持"""
        result = {
            'deposit_supported': False,
            'withdraw_supported': False,
            'networks': []
        }
        
        try:
            # 获取充值地址信息
            deposit_info = self.gate_sdk.get_deposit_address(currency=coin)
            
            if deposit_info and deposit_info.get('address'):
                result['deposit_supported'] = True
                
                # 检查multichain_addresses
                multichain = deposit_info.get('multichain_addresses', [])
                if multichain:
                    for chain_info in multichain:
                        result['networks'].append({
                            'network': chain_info.get('chain', coin),
                            'address': chain_info.get('address', ''),
                            'memo_required': bool(chain_info.get('payment_id'))
                        })
                else:
                    # 单网络
                    result['networks'].append({
                        'network': coin,
                        'address': deposit_info.get('address', ''),
                        'memo_required': False
                    })
                
                # Gate.io有充值地址通常也支持提现
                result['withdraw_supported'] = True
                
        except Exception as e:
            if 'whitelist' not in str(e).lower():
                # 非IP白名单问题，可能是币种不支持
                pass
                
        return result
    
    def _find_common_networks(self, mexc_networks: List[Dict], gate_networks: List[Dict]) -> List[str]:
        """找出共同支持的网络"""
        mexc_nets = {net['network'].upper() for net in mexc_networks}
        gate_nets = {net['network'].upper() for net in gate_networks}
        
        # 网络名称映射（处理不同交易所的命名差异）
        network_aliases = {
            'BTC': ['BTC', 'BITCOIN', 'BITCOIN网络'],
            'ETH': ['ETH', 'ETHEREUM', 'ERC20', 'ETHEREUM(ERC20)'],
            'BSC': ['BSC', 'BEP20', 'BNB', 'BNB SMART CHAIN(BEP20)', 'BNB SMART CHAIN'],
            'TRX': ['TRX', 'TRON', 'TRC20', 'TRON(TRC20)'],
            'MATIC': ['MATIC', 'POLYGON', 'POLYGON(MATIC)'],
            'AVAX': ['AVAX', 'AVALANCHE', 'AVALANCHE C CHAIN(AVAX CCHAIN)'],
            'XLM': ['XLM', 'STELLAR', 'STELLAR(XLM)'],  # 添加XLM映射
            'DOGE': ['DOGE', 'DOGECOIN', 'DOGECOIN网络'],  # DOGE原生网络
            'LTC': ['LTC', 'LITECOIN', 'LITECOIN(LTC)'],
            'ADA': ['ADA', 'CARDANO', 'CARDANO(ADA)'],
            'DOT': ['DOT', 'POLKADOT', 'POLKADOT(DOT)'],
            'ATOM': ['ATOM', 'COSMOS', 'COSMOS(ATOM)'],
        }
        
        common = []
        for mexc_net in mexc_nets:
            for gate_net in gate_nets:
                if mexc_net == gate_net:
                    common.append(mexc_net)
                else:
                    # 检查别名匹配
                    for canonical, aliases in network_aliases.items():
                        if mexc_net in aliases and gate_net in aliases:
                            common.append(canonical)
                            break
        
        return list(set(common))
    
    def _evaluate_compatibility(self, report: Dict) -> Dict[str, any]:
        """综合评估兼容性"""
        result = {
            'compatible': False,
            'risk_level': 'HIGH',
            'issues': [],
            'recommendations': []
        }
        
        # 检查基本交易支持
        if not report['mexc_trading']:
            result['issues'].append('MEXC不支持该交易对')
        if not report['gate_trading']:
            result['issues'].append('Gate.io不支持该交易对')
            
        # 检查充提现支持
        if not report['mexc_deposit']:
            result['issues'].append('MEXC不支持充值')
        if not report['mexc_withdraw']:
            result['issues'].append('MEXC不支持提现')
        if not report['gate_deposit']:
            result['issues'].append('Gate.io不支持充值')
        if not report['gate_withdraw']:
            result['issues'].append('Gate.io不支持提现')
            
        # 检查网络兼容性
        if not report['common_networks']:
            result['issues'].append('两个交易所没有共同支持的网络')
        
        # 综合判断
        basic_requirements = [
            report['mexc_trading'],
            report['gate_trading'], 
            report['mexc_deposit'],
            report['mexc_withdraw'],
            report['gate_deposit'],
            report['gate_withdraw'],
            len(report['common_networks']) > 0
        ]
        
        compatible_count = sum(basic_requirements)
        
        if compatible_count == 7:
            result['compatible'] = True
            result['risk_level'] = 'LOW'
            result['recommendations'].append('✅ 完全兼容，可以安全进行套利')
        elif compatible_count >= 5:
            result['compatible'] = True
            result['risk_level'] = 'MEDIUM' 
            result['recommendations'].append('⚠️ 基本兼容，但建议先小额测试')
        else:
            result['compatible'] = False
            result['risk_level'] = 'HIGH'
            result['recommendations'].append('❌ 不建议套利，风险过高')
            
        return result
    
    def batch_check_compatibility(self, symbols: List[str]) -> Dict[str, Dict]:
        """批量检查币种兼容性"""
        results = {}
        
        print(f"🔍 开始批量检查{len(symbols)}个币种的兼容性...")
        
        # 分组显示进度，每50个为一组
        batch_size = 50
        compatible_count = 0
        risky_count = 0
        failed_count = 0
        
        for i, symbol in enumerate(symbols, 1):
            # 每50个显示详细进度
            if i <= 50 or i % 50 == 0 or i == len(symbols):
                print(f"[{i:>4}/{len(symbols)}] 🔍 检查 {symbol}...")
            
            try:
                result = self.check_coin_full_compatibility(symbol)
                results[symbol] = result
                
                # 统计结果
                if result['compatible']:
                    if result['risk_level'] == 'LOW':
                        compatible_count += 1
                        status_icon = "✅"
                    else:
                        risky_count += 1
                        status_icon = "⚠️"
                else:
                    failed_count += 1
                    status_icon = "❌"
                
                # 显示简要结果（前50个或每50个倍数）
                if i <= 50 or i % 50 == 0 or i == len(symbols):
                    risk = result['risk_level']
                    networks = len(result.get('common_networks', []))
                    print(f"    {status_icon} {symbol}: {risk}风险, {networks}个共同网络")
                
                # API限制控制 - 更精细的控制
                if i % 20 == 0:  # 每20个暂停
                    print(f"    ⏳ 已检查{i}个 (✅{compatible_count} ⚠️{risky_count} ❌{failed_count}), 暂停2秒...")
                    time.sleep(2)
                elif i % 5 == 0:  # 每5个短暂停
                    time.sleep(0.5)
                    
            except Exception as e:
                failed_count += 1
                error_msg = str(e)[:50]
                if i <= 50 or i % 50 == 0:
                    print(f"    ❌ {symbol}: 检查失败 - {error_msg}")
                
                results[symbol] = {
                    'symbol': symbol,
                    'compatible': False,
                    'risk_level': 'HIGH',
                    'issues': [f'检查失败: {error_msg}'],
                    'mexc_trading': False,
                    'gate_trading': False,
                    'mexc_deposit': False,
                    'mexc_withdraw': False,
                    'gate_deposit': False,
                    'gate_withdraw': False,
                    'common_networks': []
                }
                
                # 连续失败过多时增加延迟
                if failed_count > 0 and failed_count % 10 == 0:
                    print(f"    ⚠️ 连续失败较多，增加延迟...")
                    time.sleep(5)
        
        # 最终统计
        print(f"\n" + "="*50)
        print(f"📊 批量检查完成统计:")
        print(f"  总计检查: {len(symbols)} 个币种")
        print(f"  ✅ 高度兼容: {compatible_count} 个")
        print(f"  ⚠️ 基本兼容: {risky_count} 个") 
        print(f"  ❌ 不兼容/失败: {failed_count} 个")
        print(f"  🎯 总兼容率: {((compatible_count + risky_count) / len(symbols) * 100):.1f}%")
        print("="*50)
        
        return results
    
    def generate_compatibility_report(self, results: Dict[str, Dict]) -> str:
        """生成兼容性报告"""
        
        compatible_coins = []
        risky_coins = []
        incompatible_coins = []
        
        for symbol, result in results.items():
            if result['compatible']:
                if result['risk_level'] == 'LOW':
                    compatible_coins.append((symbol, result))
                else:
                    risky_coins.append((symbol, result))
            else:
                incompatible_coins.append((symbol, result))
        
        report = []
        report.append("=" * 80)
        report.append("🔍 币种兼容性检查报告")
        report.append("=" * 80)
        
        report.append(f"\n📊 检查汇总:")
        report.append(f"  总数: {len(results)}个币种")
        report.append(f"  ✅ 完全兼容: {len(compatible_coins)}个")
        report.append(f"  ⚠️ 有风险: {len(risky_coins)}个")
        report.append(f"  ❌ 不兼容: {len(incompatible_coins)}个")
        
        if compatible_coins:
            report.append(f"\n✅ 推荐套利币种 ({len(compatible_coins)}个):")
            report.append("-" * 60)
            for symbol, result in compatible_coins:
                networks = ', '.join(result.get('common_networks', []))
                report.append(f"  {symbol:12} 网络: {networks}")
        
        if risky_coins:
            report.append(f"\n⚠️ 谨慎套利币种 ({len(risky_coins)}个):")
            report.append("-" * 60)
            for symbol, result in risky_coins:
                issues = '; '.join(result.get('issues', [])[:2])
                report.append(f"  {symbol:12} 问题: {issues}")
        
        if incompatible_coins:
            report.append(f"\n❌ 不建议套利币种 ({len(incompatible_coins)}个):")
            report.append("-" * 60)
            for symbol, result in incompatible_coins[:10]:  # 只显示前10个
                issues = '; '.join(result.get('issues', [])[:2])
                report.append(f"  {symbol:12} 问题: {issues}")
        
        report.append("\n💡 使用建议:")
        report.append("1. 优先选择'完全兼容'的币种进行套利")
        report.append("2. '有风险'币种建议先小额测试")
        report.append("3. 避免使用'不兼容'的币种")
        report.append("4. 定期重新检查币种状态")
        
        report.append("=" * 80)
        
        return "\n".join(report)