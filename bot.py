import os
import yaml
import logging
import requests
import base64
import io  
import signal
import sys
import telegram
import socketio


from openai import OpenAI
from crisp_api import Crisp
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, Defaults, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from telegram.error import BadRequest

import handler
# 全局变量来控制程序运行状态
is_running = True

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
# set higher logging level for httpx to avoid all GET and POST requests being logged
logging.getLogger("httpx").setLevel(logging.WARNING)

# Load Config
try:
    f = open('config.yml', 'r')
    config = yaml.safe_load(f)
except FileNotFoundError as error:
    logging.warning('没有找到 config.yml，请复制 config.yml.example 并重命名为 config.yml')
    exit(1)

# 初始化昵称配置
nicknames = config.get('nicknames', {
    'human_agent': '人工客服',
    'ai_agent': 'AI客服',
    'system_message': '系统消息'
})

# Connect Crisp
try:
    crispCfg = config['crisp']
    client = Crisp()
    client.set_tier("plugin")
    client.authenticate(crispCfg['id'], crispCfg['key'])
    client.plugin.get_connect_account()
    client.website.get_website(crispCfg['website'])
except Exception as error:
    logging.warning('无法连接 Crisp 服务，请确认 Crisp 配置项是否正确')
    exit(1)

# Connect OpenAI
try:
    openai = OpenAI(api_key=config['openai']['apiKey'], base_url='https://api.openai.com/v1')
    openai.models.list()  # 测试连接
except Exception as error:
    logging.warning('无法连接 OpenAI 服务，智能化回复将不会使用')
    logging.error(f"OpenAI 连接错误: {str(error)}")  # 添加详细错误日志
    openai = None

# 修改 socket.io 客户端配置
sio = socketio.AsyncClient(
    reconnection=True,
    reconnection_attempts=5,  # 限制重连次数
    reconnection_delay=1,     # 初始重连延迟
    reconnection_delay_max=60,  # 最大重连延迟
    logger=True,
    request_timeout=30,       # 请求超时时间
    handle_sigint=False       # 禁用默认的 SIGINT 处理
)

def changeButton(conversation_id, boolean, completed=False):
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    text='关闭 AI 回复' if boolean else '打开 AI 回复',
                    callback_data=f'{conversation_id},{boolean}'
                ),
                InlineKeyboardButton(
                    text='已完成' if completed else '标记为已完成',
                    callback_data=f'uncomplete_session_{conversation_id}' if completed else f'complete_session_{conversation_id}'
                )
            ]
        ]
    )

async def onReply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message

    if msg.chat_id != config['bot']['groupId']:
        return
        
    try:
        # 检查消息是否有话题ID
        if not msg.message_thread_id:
            logging.warning("消息没有话题ID，可能是在主频道发送")
            return
        # 先从内存中查找，如果找不到则从文件加载
        session_id = None
        for sid, data in context.bot_data.items():
            if data.get('topicId') == msg.message_thread_id:
                session_id = sid
                break
                
        if not session_id:
            # 从文件重新加载映射
            mapping = handler.load_session_mapping()
            for sid, data in mapping.items():
                if data['topic_id'] == msg.message_thread_id:
                    session_id = sid
                    # 更新到内存
                    context.bot_data[sid] = {
                        'topicId': data['topic_id'],
                        'enableAI': data.get('enable_ai', False)
                    }
                    break
        
        if session_id:
            if msg.text:  # 处理文本消息
                query = {
                    "type": "text",
                    "content": msg.text,
                    "from": "operator",
                    "origin": "chat",
                    "user": {
                        "nickname": nicknames.get('human_agent', '人工客服'),
                        "avatar": handler.avatars.get('human_agent', 'https://example.com/default_avatar.png')
                    }
                }
                # 使用找到的 session_id 发送消息
                client.website.send_message_in_conversation(
                    config['crisp']['website'],
                    session_id,
                    query
                )
            elif msg.photo:  # 处理图片消息
                try:
                    photo_file = await msg.photo[-1].get_file()
                    image_bytes = await photo_file.download_as_bytearray()

                    # 使用新的上传函数
                    print("开始上传图片")
                    image_url = handler.upload_image_to_telegraph(io.BytesIO(image_bytes))
                    print(f"图片上传成功，URL: {image_url}")
                    
                    markdown_image = f"[![image]({image_url})]({image_url}) \n点击图片可查看高清大图"
                    
                    query = {
                        "type": "text",
                        "content": markdown_image,
                        "from": "operator",
                        "origin": "chat",
                        "user": {
                            "nickname": nicknames.get('human_agent', '人工客服'),
                            "avatar": handler.avatars.get('human_agent', 'https://example.com/default_avatar.png')
                        }
                    }
                    
                    # 使用找到的 session_id 发送消息
                    client.website.send_message_in_conversation(
                        config['crisp']['website'],
                        session_id,
                        query
                    )
                    
                except Exception as e:
                    print(f"处理图片失败: {str(e)}")
                    await msg.reply_text("发送图片失败，请稍后重试。")
                    return
        else:
            logging.error(f"未找到对应的会话 ID，话题 ID: {msg.message_thread_id}")
            
    except Exception as e:
        logging.error(f"发送消息失败: {str(e)}")

async def onChange(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Parses the CallbackQuery and updates the message text."""
    query = update.callback_query
    data = query.data.split(',')

    if data[0].startswith('complete_session_'):
        session_id = data[0].split('complete_session_')[1]
        try:
            # 使用 PATCH 请求将对话标记为已完成
            url = f"https://api.crisp.chat/v1/website/{crispCfg['website']}/conversation/{session_id}/state"
            auth = base64.b64encode(f"{crispCfg['id']}:{crispCfg['key']}".encode()).decode()
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Basic {auth}",
                "X-Crisp-Tier": "plugin"
            }
            payload = {"state": "resolved"}
            response = requests.patch(url, json=payload, headers=headers)
            response.raise_for_status()
            await query.answer('对话已标记为完成')
            # 更新按钮为 "已完成"
            session = context.bot_data.get(session_id, {})
            session["completed"] = True
            await query.edit_message_reply_markup(
                reply_markup=changeButton(session_id, session.get("enableAI", False), completed=True)
            )
        except Exception as error:
            await query.answer('无法标记对话为完成')
            logging.error(f"标记完成失败: {str(error)}")
    
    elif data[0].startswith('uncomplete_session_'):
        session_id = data[0].split('uncomplete_session_')[1]
        try:
            # 使用 PATCH 请求将对话标记为未完成
            url = f"https://api.crisp.chat/v1/website/{crispCfg['website']}/conversation/{session_id}/state"
            auth = base64.b64encode(f"{crispCfg['id']}:{crispCfg['key']}".encode()).decode()
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Basic {auth}",
                "X-Crisp-Tier": "plugin"
            }
            payload = {"state": "pending"}  # 或其他合适的状态
            response = requests.patch(url, json=payload, headers=headers)
            response.raise_for_status()
            await query.answer('已取消完成标记')
            # 更新按钮为 "标记为已完成"
            session = context.bot_data.get(session_id, {})
            session["completed"] = False
            await query.edit_message_reply_markup(
                reply_markup=changeButton(session_id, session.get("enableAI", False), completed=False)
            )
        except Exception as error:
            await query.answer('无法取消完成标记')
            logging.error(f"取消完成标记失败: {str(error)}")

    else:
        session_id = data[0]
        if openai is None:
            await query.answer('无法设置此功能')
        else:
            session = context.bot_data.get(data[0])
            session["enableAI"] = not eval(data[1])
            await query.answer()
            try:
                # 保持完成状态不变
                completed = False
                if session_id in context.bot_data:
                    completed = context.bot_data[session_id].get('completed', False)
                await query.edit_message_reply_markup(
                    changeButton(data[0], session["enableAI"], completed=completed)
                )
                # 发送提示消息给对方
                if session["enableAI"]:
                    message_content = "客服暂时无法回复您，AI客服已接入"
                else:
                    message_content = "关闭AI自动回复，人工客服已接入"
                
                query = {
                    "type": "text",
                    "content": message_content,
                    "from": "operator",
                    "origin": "chat",
                    "user": {
                        "nickname": nicknames.get('system_message', '系统消息'),
                        "avatar": handler.avatars.get('system_message', 'https://example.com/system_avatar.png')
                    }
                }
                client.website.send_message_in_conversation(
                    config['crisp']['website'],
                    session_id,
                    query
                )
            except telegram.error.BadRequest as e:
                if "Message is not modified" not in str(e):
                    logging.error(f"更新消息标记失败: {str(e)}")
            except Exception as error:
                logging.error(error)

    # 生成并发送按钮
    conversation_id = data[0]
    if 'button_sent' not in context.bot_data.get(conversation_id, {}):
        try:
            await query.message.reply_text(
                "选择操作：",
                reply_markup=changeButton(conversation_id, context.bot_data.get(conversation_id, {}).get("enableAI", False))
            )
            context.bot_data.setdefault(conversation_id, {})['button_sent'] = True
        except Exception as e:
            logging.error(f"发送按钮消息失败: {str(e)}")
        

def force_exit(signum, frame):
    print("\n强制退出程序...")
    os._exit(0)

def main():
    try:
        # 设置信号处理
        signal.signal(signal.SIGINT, force_exit)
        signal.signal(signal.SIGTERM, force_exit)

        logging.info("正在初始化 Bot...")
        app = Application.builder().token(config['bot']['token']).defaults(Defaults(parse_mode='HTML')).build()
        
        # 加载并同步会话映射
        try:
            session_mapping = handler.load_session_mapping()
            for session_id, data in session_mapping.items():
                if isinstance(data, dict) and 'topic_id' in data:
                    app.bot_data[session_id] = {
                        'topicId': data['topic_id'],
                        'messageId': data.get('message_id'),
                        'enableAI': data.get('enable_ai', False),
                        'first_message': False,  # 设置为 False 避免重复发送提示
                        'completed': False  # 添加完成状态
                    }
                    logging.info(f"已恢复会话映射: {session_id} -> {data['topic_id']}")
        except Exception as e:
            logging.error(f"加载会话映射失败: {str(e)}")

        if os.getenv('RUNNER_NAME') is not None:
            return
            
        # 修改回调处理器的注册
        async def callback_handler(update, context):
            try:
                query = update.callback_query
                message = query.message
                
                # 检查是否是管理命令
                if query.data.startswith('admin_'):
                    # 管理命令只在主话题中响应
                    if not message.is_topic_message:  # 如果不是话题消息，说明是在主话题中
                        await handler.handle_admin_callback(update, context)
                    else:
                        await query.answer("此操作只能在主话题中使用")
                else:
                    # 其他回调正常处理
                    await onChange(update, context)
                    
            except Exception as e:
                logging.error(f"回调处理出错: {str(e)}")

        logging.info("正在注册处理器...")
        # 注册消息处理器，合并图片和文本处理
        app.add_handler(MessageHandler(
            (filters.TEXT | filters.PHOTO) & filters.Chat(chat_id=config['bot']['groupId']),
            onReply,
            block=True
        ), group=1)
        
        # 注册关键字处理器
        app.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND & filters.Chat(chat_id=config['bot']['groupId']),
            handler.handle_keyword_input,
            block=True
        ), group=2)
        
        app.add_handler(CallbackQueryHandler(callback_handler))
        
        logging.info("正在启动 Bot...")
        app.job_queue.run_once(handler.exec, 5, name='RTM')
        print("Bot 已启动。按 Ctrl+C 停止。")
        app.run_polling(drop_pending_updates=True)
        
    except Exception as error:
        logging.error(f"启动失败，详细错误: {str(error)}")
        logging.warning('无法启动 Telegram Bot，请确认 Bot Token 是否正确，或者是否能连接 Telegram 服务器')
        exit(1)

if __name__ == "__main__":
    main()
