import os
import yaml
import logging
import requests
import base64
import io  
import signal
import sys
import telegram


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
    openai.models.list()
except Exception as error:
    logging.warning('无法连接 OpenAI 服务，智能化回复将不会使用')
    openai = None

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
                    callback_data=f'complete_session_{conversation_id}'
                )
            ]
        ]
    )

async def onReply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message

    if msg.chat_id != config['bot']['groupId']:
        return
    for conversation_id in context.bot_data:
        if context.bot_data[conversation_id]['topicId'] == msg.message_thread_id:
            if msg.text:  # 处理文本消息
                query = {
                    "type": "text",
                    "content": msg.text,
                    "from": "operator",
                    "origin": "chat",
                    "user": {
                        "nickname": '人工客服',
                        "avatar": handler.avatars.get('human_agent', 'https://example.com/default_avatar.png')
                    }
                }
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
                            "nickname": '人工客服',
                            "avatar": handler.avatars.get('human_agent', 'https://example.com/default_avatar.png')
                        }
                    }
                except Exception as e:
                    print(f"处理图片失败: {str(e)}")
                    await msg.reply_text("发送图片失败，请稍后重试。")
                    return
            else:
                await msg.reply_text("不支持的消息类型。")
                return

            client.website.send_message_in_conversation(
                config['crisp']['website'],
                conversation_id,
                query
            )
            try:
                # 直接生成新的回复标记
                new_reply_markup = changeButton(conversation_id, context.bot_data[conversation_id].get("enableAI", False))

                # 尝试更新消息的回复标记
                await context.bot.edit_message_reply_markup(
                    chat_id=msg.chat_id,
                    message_id=context.bot_data[conversation_id]['messageId'],
                    reply_markup=new_reply_markup
                )
            except telegram.error.BadRequest as e:
                if "Message is not modified" not in str(e):
                    # 如果错误不是"消息未修改"，则记录错误
                    logging.error(f"更新消息标记失败: {str(e)}")
                # 如果是"消息未修改"错误，我们可以安全地忽略它
            except Exception as e:
                # 捕获其他可能的异常
                logging.error(f"更新消息时出错: {str(e)}")
            return

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
            response.raise_for_status()  # 如果响应状态码不是 200，抛出异常
            await query.answer('对话已标记为完成')
            # 更新按钮为 "已完成"
            await query.edit_message_reply_markup(
                reply_markup=changeButton(session_id, context.bot_data[session_id].get("enableAI", False), completed=True)
            )
        except requests.exceptions.RequestException as error:
            await query.answer('无法标记对话为完成')
            await query.message.reply_text(f"请求失败: {error}\n响应内容: {response.text}")
        except Exception as error:
            await query.answer('无法标记对话为完成')
            await query.message.reply_text(f"未知错误: {error}")
    else:
        session_id = data[0]  # 从 data 中解析 session_id
        if openai is None:
            await query.answer('无法设置此功能')
        else:
            session = context.bot_data.get(data[0])
            session["enableAI"] = not eval(data[1])
            await query.answer()
            try:
                await query.edit_message_reply_markup(changeButton(data[0], session["enableAI"]))
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
                        "nickname": '系统消息',
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

        app = Application.builder().token(config['bot']['token']).defaults(Defaults(parse_mode='HTML')).build()
        
        if os.getenv('RUNNER_NAME') is not None:
            return
            
        # 定义一个回调处理函数
        async def callback_handler(update, context):
            query = update.callback_query
            if query.data.startswith('admin_'):
                await handler.handle_admin_callback(update, context)
            else:
                await onChange(update, context)

        # 注册处理器 - 调整顺序和优先级
        app.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND & filters.Chat(chat_id=config['bot']['groupId']) & 
            filters.ChatType.GROUP | filters.ChatType.SUPERGROUP,
            handler.handle_keyword_input,
            block=True
        ), group=1)  # 给予更高优先级
        
        app.add_handler(MessageHandler(filters.TEXT | filters.PHOTO, onReply), group=2)
        app.add_handler(CallbackQueryHandler(callback_handler))
        
        app.job_queue.run_once(handler.exec, 5, name='RTM')
        print("Bot 已启动。按 Ctrl+C 停止。")
        app.run_polling(drop_pending_updates=True)
        
    except Exception as error:
        logging.warning('无法启动 Telegram Bot，请确认 Bot Token 是否正确，或者是否能连接 Telegram 服务器')
        exit(1)

if __name__ == "__main__":
    main()
