#!/bin/bash
# 环境设置和问题修复脚本

echo "🔧 环境和API问题修复"
echo "===================="

# 1. 检查conda环境
echo "1. 检查conda环境："
if command -v conda >/dev/null 2>&1; then
    echo "✅ Conda已安装"
    echo "当前环境列表："
    conda info --envs 2>/dev/null || echo "⚠️ 无法获取环境列表"
    
    echo ""
    echo "激活lbankbot环境命令："
    echo "conda activate lbankbot"
else
    echo "❌ Conda未找到"
fi

# 2. 检查系统时间
echo ""
echo "2. 检查系统时间："
echo "本地时间: $(date)"
echo "UTC时间:  $(date -u)"

# 3. 时间同步建议
echo ""
echo "3. API时间戳问题修复："
echo "如果出现 'Timestamp outside recvWindow' 错误："
echo "• macOS: sudo sntp -sS time.apple.com"
echo "• Linux: sudo ntpdate -s time.nist.gov"
echo "• Windows: w32tm /resync"

# 4. 环境切换指导
echo ""
echo "4. 环境切换步骤："
echo "conda activate lbankbot"
echo "cd /Users/huangweizhu/web3_airdrop/bot/makeMoneyBot"
echo "python arbitrage_bot.py"

# 5. 依赖检查
echo ""
echo "5. 检查Python依赖："
python -c "
import sys
print(f'Python路径: {sys.executable}')

modules = ['ccxt', 'yaml', 'requests']
for module in modules:
    try:
        __import__(module)
        print(f'✅ {module}')
    except ImportError:
        print(f'❌ {module} - 需要安装: pip install {module}')
"

echo ""
echo "6. 如果在lbankbot环境中缺少依赖："
echo "conda activate lbankbot"
echo "pip install ccxt PyYAML requests"