import os
import sys
import asyncio
import requests
from telethon import TelegramClient
from telethon.tl.custom.message import Message
from typing import Dict, Any, Tuple
import re

# Windows事件循环策略，兼容win系统运行
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# ================= 配置区域 =================
TG_API_ID = os.getenv('TG_API_ID')
TG_API_HASH = os.getenv('TG_API_HASH')
TG_BOT_TOKEN = os.getenv('TG_BOT_TOKEN')    # 你的通知机器人 Token
TG_CHAT_ID = os.getenv('TG_CHAT_ID')        # 你的个人或群组 Chat ID
TG_CHANNEL = '@cloudcatgroup'               # 签到目标频道用户名, 格式: @username
CHANNEL_BOT_ID = 7694509436                 # 签到目标频道签到机器人的 ID
CHECK_WAIT_TIME = 8                         # 等待机器人回复的时间（秒）
DEFAULT_GAINED_POINTS = "已签"               # 获得积分的默认值
DEFAULT_TOTAL_POINTS = "未知"                # 当前总分的默认值
# ============================================

# 定义颜色和符号 (用于日志美化)
COLORS: Dict[str, str] = {
    'red': '\033[91m', 'green': '\033[92m', 'yellow': '\033[93m',
    'cyan': '\033[96m', 'reset': '\033[0m'
}
SYMBOLS: Dict[str, str] = {'check': '✓', 'warning': '⚠', 'arrow': '➜', 'error': '✗'}

# 日志函数
def log(color: str, symbol: str, message: str):
    print(f"{COLORS[color]}{SYMBOLS[symbol]} {message}{COLORS['reset']}")

# 发送 Telegram 消息通知模板
def send_tg_notification(status: str, gained: str, total: str):
    if not (TG_BOT_TOKEN and TG_CHAT_ID):
        log('yellow', 'warning', "未设置 TG_BOT_TOKEN 或 TG_CHAT_ID，跳过通知")
        return

    channel_link = TG_CHANNEL.replace('@', 't.me/') if TG_CHANNEL.startswith('@') else TG_CHANNEL # 构造频道链接
    status_emoji = "✅" if status == "成功" else ("⭐" if status == "今日已签到" else "❌") # 状态 Emoji
    notification_text = (
        f"🎉 *Cloud Cat 签到通知* 🎉\n"
        f"====================\n"
        f"{status_emoji} 状态: {status}\n"
        f"📢 频道: [{TG_CHANNEL}]({channel_link})\n"
        f"📌 今日签到积分: {gained}\n"
        f"📊 您的总积分: {total}"
    )
    
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    payload: Dict[str, Any] = {
        'chat_id': TG_CHAT_ID,
        'text': notification_text,
        'parse_mode': 'Markdown'
    }

    try:
        requests.post(url, data=payload, timeout=10).raise_for_status()
    except requests.exceptions.RequestException as e:
        log('red', 'error', f"Telegram 通知发送失败: {e}")

# 解析今日签到积分和总积分
def parse_points_from_message(message_text: str, is_points_command_reply: bool) -> Tuple[str, str]:
    gained_points = DEFAULT_GAINED_POINTS
    total_points = DEFAULT_TOTAL_POINTS
    
    if is_points_command_reply: # 今日已签到的情况
        gained_match = re.search(r'CheckInAddPoint[:：]\s*(\d+\.?\d*)\s*⭐?', message_text, re.IGNORECASE)
        total_match = re.search(r'(?:当前积分[:：]|current points[:：]\s*)(\d+\.?\d*)', message_text, re.IGNORECASE)
    else: # 今日未签到的情况
        gained_match = re.search(r'(?:获得|you got)\s*(\d+\.?\d*)\s?⭐', message_text, re.IGNORECASE)
        total_match = re.search(r'(?:当前积分[:：]|current points:\s*)(\d+\.?\d*)\s?⭐', message_text, re.IGNORECASE)

    if gained_match:
        gained_points = f"{gained_match.group(1)}⭐"
    if total_match:
        try:
            total_score = float(total_match.group(1))
            total_points = f"{int(total_score)}⭐"  # 转换为整数并添加⭐
        except ValueError:
            pass

    return gained_points, total_points

# 等待并获取目标机器人最新回复
async def get_bot_reply(client: TelegramClient, channel_entity: Any, check_limit: int) -> Message | None:
    log('cyan', 'arrow', f"等待 {CHECK_WAIT_TIME} 秒后开始查找机器人回复...")
    await asyncio.sleep(CHECK_WAIT_TIME)
    log('cyan', 'arrow', f"开始查找最近 {check_limit} 条消息...")
    message_count = 0
    
    async for msg in client.iter_messages(channel_entity, limit=check_limit):
        message_count += 1
        if isinstance(msg, Message) and msg.sender_id == CHANNEL_BOT_ID:
            log('green', 'check', f"找到目标机器人 (ID: {CHANNEL_BOT_ID}) 的回复")
            return msg
    
    log('yellow', 'warning', f"在最近 {message_count} 条消息中未找到目标机器人 (ID: {CHANNEL_BOT_ID}) 的回复")
    return None

# 执行频道签到并判断结果的主逻辑
async def check_in():
    # 检查核心登录变量
    required_vars = {'TG_API_ID': TG_API_ID, 'TG_API_HASH': TG_API_HASH}
    missing_vars = [name for name, val in required_vars.items() if not val]
    
    if missing_vars:
        err_msg = f"TG 登录失败：缺少必要的变量: {', '.join(missing_vars)}！请检查 GitHub Secrets 设置"
        log('red', 'error', err_msg)
        sys.exit(1)

    session_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'tg_session.session')
    
    log('cyan', 'arrow', "启动 TG 并尝试登录")
    status = "失败"
    gained_points = DEFAULT_GAINED_POINTS
    total_points = DEFAULT_GAINED_POINTS
    check_limit = 20  # 消息查找范围

    # 签到逻辑：先发送 /checkin，成功则直接获取积分；若为“已签到”则发送 /points 获取积分
    try:
        async with TelegramClient(session_path, TG_API_ID, TG_API_HASH) as client:
            await client.start()

            channel_entity = await client.get_entity(TG_CHANNEL)
            log('cyan', 'arrow', f"已成功连接频道：{channel_entity.title}")

            # 先发送 /checkin 直接签到
            log('cyan', 'arrow', "发送 /checkin 命令进行签到")
            await client.send_message(channel_entity, '/checkin')
            checkin_reply = await get_bot_reply(client, channel_entity, check_limit)
            if checkin_reply and checkin_reply.text:
                reply_text = checkin_reply.text
                log('green', 'check', f"收到 /checkin 回复，内容:\n{reply_text}")
                
                # 检查是否签到成功
                if '成功' in reply_text or 'successful' in reply_text:
                    status = "成功"
                    log('green', 'check', "判断为：签到成功")
                    gained_points, total_points = parse_points_from_message(reply_text, False)
                
                # 检查是否已签到
                elif '您今天已经签到过了' in reply_text or '今天已经签到' in reply_text or '今日已签到' in reply_text:
                    status = "今日已签到"
                    log('yellow', 'warning', "判断为：今日已签到，发送 /points 获取积分详情")
                    await client.send_message(channel_entity, '/points')
                    points_reply = await get_bot_reply(client, channel_entity, check_limit)
                    
                    if points_reply and points_reply.text:
                        points_text = points_reply.text
                        log('green', 'check', f"收到 /points 回复，内容:\n{points_text}")
                        gained_points, total_points = parse_points_from_message(points_text, True)
                    else:
                        log('red', 'error', "发送 /points 后未收到机器人回复")
                else:
                    status = "失败"
                    log('red', 'error', "未找到预期的签到成功或已签到关键词")
            else:
                status = "失败"
                log('red', 'error', "发送 /checkin 后未收到目标机器人的回复")

    except Exception as e:
        err_msg = f"连接或执行过程中出现严重错误: {type(e).__name__} - {str(e)}"
        log('red', 'error', err_msg)
        log('yellow', 'warning', "请检查 API 配置、频道名称是否正确, 及 Session 文件是否有效")
        sys.exit(1)

    # === 最终通知 ===
    log('cyan', 'arrow', f"最终结果 - 状态: {status}, 今日积分: {gained_points}, 总积分: {total_points}")
    if status == "失败":
        final_msg = "签到失败或无法确认, 请查看日志获取详细错误"
        log('red', 'error', final_msg)
        send_tg_notification(status, gained_points, total_points)
    else:
        send_tg_notification(status, gained_points, total_points)
        
    log('green', 'check', "任务结束")

if __name__ == '__main__':
    log('cyan', 'arrow', "开始执行频道签到任务")
    asyncio.run(check_in())
