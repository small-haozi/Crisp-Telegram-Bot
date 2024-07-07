import os
import yaml
import logging
import requests
import base64

from openai import OpenAI
from crisp_api import Crisp
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, Defaults, MessageHandler, filters, ContextTypes, CallbackQueryHandler

import handler

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levellevel)s - %(message)s", level=logging.INFO
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
            query = {
                "type": "text",
                "content": msg.text,
                "from": "operator",
                "origin": "chat",
                "user": {
                    "nickname": '人工客服',
                    "avatar": 'https://i.111666.best/image/cAxQJWIjQt8mHE42kOUzXu.jpg'
                }
            }
            client.website.send_message_in_conversation(
                config['crisp']['website'],
                conversation_id,
                query
            )
            # 重置按钮为 "标记为已完成"
            await context.bot.edit_message_reply_markup(
                chat_id=msg.chat_id,
                message_id=context.bot_data[conversation_id]['messageId'],
                reply_markup=changeButton(conversation_id, context.bot_data[conversation_id].get("enableAI", False))
            )
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
        if openai is None:
            await query.answer('无法设置此功能')
        else:
            session = context.bot_data.get(data[0])
            session["enableAI"] = not eval(data[1])
            await query.answer()
            try:
                await query.edit_message_reply_markup(changeButton(data[0], session["enableAI"]))
            except Exception as error:
                logging.error(error)

    # 生成并发送按钮
    conversation_id = data[0]
    if 'button_sent' not in context.bot_data[conversation_id]:
        await query.message.reply_text(
            "选择操作：",
            reply_markup=changeButton(conversation_id, context.bot_data[conversation_id].get("enableAI", False))
        )
        context.bot_data[conversation_id]['button_sent'] = True

def main():
    try:
        app = Application.builder().token(config['bot']['token']).defaults(Defaults(parse_mode='HTML')).build()
        # 启动 Bot
        if os.getenv('RUNNER_NAME') is not None:
            return
        app.add_handler(MessageHandler(filters.TEXT, onReply))
        app.add_handler(CallbackQueryHandler(onChange))
        app.job_queue.run_once(handler.exec, 5, name='RTM')
        app.run_polling(drop_pending_updates=True)
    except Exception as error:
        logging.warning('无法启动 Telegram Bot，请确认 Bot Token 是否正确，或者是否能连接 Telegram 服务器')
        exit(1)

if __name__ == "__main__":
    main()
