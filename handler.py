import bot
import json
import base64
import socketio
import requests
import logging
import io
from location_names import translation_dict  # 导入词典文件
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from telegram.ext import ContextTypes
from telegram.ext import MessageHandler, filters
from PIL import Image
from contextlib import contextmanager
import yaml
import subprocess
import os
import asyncio
import sys



config = bot.config
client = bot.client
openai = bot.openai
changeButton = bot.changeButton
groupId = config["bot"]["groupId"]
websiteId = config["crisp"]["website"]
payload = config["openai"]["payload"]
# 添加这一行来初始化avatars
avatars = config.get('avatars', {})



def print_enabled_image_services():
    enabled_services = config.get('image_upload', {}).get('enabled_services', {})
    
    logging.info("图床服务状态:")
    if enabled_services:
        for service, enabled in enabled_services.items():
            status = "开启" if enabled else "关闭"
            logging.info(f"{service} - {status}")
    else:
        logging.warning("警告：未找到任何图床服务配置")

    # 检查是否有任何服务被启用
    if not any(enabled_services.values()):
        logging.warning("警告：当前没有启用任何图床服务")

@contextmanager
def api_upload_context(api_type):
    logging.info(f"开始尝试上传到 {api_type}")
    try:
        yield
    except Exception as e:
        logging.error(f"上传到 {api_type} 失败: {str(e)}")
    finally:
        logging.info(f"结束 {api_type} 上传尝试")

# 新增函数：上传图片到图床
def upload_image_to_telegraph(image_data):
    enabled_services = config.get('image_upload', {}).get('enabled_services', {})
    apis = [
        {
            "url": "https://api.imgbb.com/1/upload",
            "type": "imgbb", 
            "enabled": enabled_services.get('imgbb', True),
            "process_response": lambda r: r.json()['data']['url']
        },
        {
            "url": "https://file.sang.pub/api/upload",
            "type": "sang_pub",
            "enabled": enabled_services.get('sang_pub', False),
            "process_response": lambda r: r.text.strip()
        },
        {
            "url": f"https://api.cloudinary.com/v1_1/{config.get('image_upload', {}).get('cloudinary', {}).get('cloud_name', '')}/image/upload",
            "type": "cloudinary",
            "enabled": enabled_services.get('cloudinary', False),
            "process_response": lambda r: r.json()['secure_url']
        },
        {
            "url": "https://telegra.ph/upload",
            "type": "telegraph",
            "enabled": enabled_services.get('telegraph', False),  # 默认设置为禁用
            "process_response": lambda r: 'https://telegra.ph' + r.json()[0]['src']
        }
    ]

    # 验证图片数据
    if not isinstance(image_data, (bytes, io.BytesIO)):
        raise ValueError("image_data 必须是 bytes 或 BytesIO 对象")
    
    image_bytes = image_data.getvalue() if isinstance(image_data, io.BytesIO) else image_data

    # 检测图片格式
    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            img_format = img.format.lower()
    except Exception as e:
        logging.error(f"无法检测图片格式: {str(e)}")
        img_format = 'jpeg'

    for api in apis:
        if not api["enabled"]:
            logging.info(f"跳过已禁用的图床服务: {api['type']}")
            continue
            
        with api_upload_context(api["type"]):
            try:
                if api["type"] == "imgbb":
                    imgbb_api_key = config.get('image_upload', {}).get('imgbb_api_key')
                    if not imgbb_api_key:
                        logging.warning("ImgBB API密钥未设置")
                        continue
                        
                    files = {'image': (f'image.{img_format}', image_bytes, f'image/{img_format}')}
                    params = {
                        'key': imgbb_api_key,
                        'expiration': config.get('image_upload', {}).get('imgbb_expiration', 0)
                    }
                    response = requests.post(api["url"], files=files, params=params, timeout=10)
                
                elif api["type"] == "cloudinary":
                    cloudinary_config = config.get('image_upload', {}).get('cloudinary', {})
                    if not all([cloudinary_config.get('cloud_name'), cloudinary_config.get('upload_preset')]):
                        logging.warning("Cloudinary配置不完整")
                        continue
                        
                    data = {
                        "file": f"data:image/{img_format};base64,{base64.b64encode(image_bytes).decode('utf-8')}",
                        "upload_preset": cloudinary_config['upload_preset']
                    }
                    response = requests.post(api["url"], json=data, timeout=10)
                
                else:
                    files = {'file': (f'image.{img_format}', image_bytes, f'image/{img_format}')}
                    response = requests.post(api["url"], files=files, timeout=10)

                response.raise_for_status()
                image_url = api["process_response"](response)
                
                if not image_url or not image_url.startswith('http'):
                    raise ValueError(f"无效的图片URL: {image_url}")
                    
                logging.info(f"成功上传到 {api['type']}: {image_url}")
                return image_url

            except requests.exceptions.RequestException as e:
                logging.error(f"上传到 {api['type']} 失败: {str(e)}")
                if hasattr(e, 'response') and e.response:
                    logging.error(f"错误详情: {e.response.text}")
            except Exception as e:
                logging.error(f"上传到 {api['type']} 时发生未知错误: {str(e)}")
                
    raise Exception("所有启用的图片上传API都失败了")


def getKey(content: str):
    if len(config["autoreply"]) > 0:
        for x in config["autoreply"]:
            keyword = x.split("|")
            for key in keyword:
                if key in content:
                    return True, config["autoreply"][x]
    return False, None

def escape_markdown(text, preserve_backticks=False):
    """转义 Markdown 特殊字符
    Args:
        text: 要转义的文本
        preserve_backticks: 是否保留反引号的特殊格式
    """
    if not text:  # 处理空值情况
        return ""
        
    # 将文本转换为字符串
    text = str(text)
    
    # 定义需要转义的特殊字符
    special_chars = [
        '_', '*', '[', ']', '(', ')', '~', '>', '#', '+', 
        '-', '=', '|', '{', '}', '.', '!', ',', ':', ';'
    ]
    
    # 如果不保留反引号格式，将反引号加入转义列表
    if not preserve_backticks:
        special_chars.append('`')
    
    # 转义所有特殊字符
    for char in special_chars:
        text = text.replace(char, f'\\{char}')
        
    return text

def getMetas(sessionId):
    conversation = client.website.get_conversation(websiteId, sessionId)
    
    # 使用列表推导式构建信息流
    flow = ['*Crisp消息推送*']
    
    if conversation.get("error"):
        return '\n'.join(flow + ['无法获取会话信息'])

    data = conversation.get("data", {})
    metas = client.website.get_conversation_metas(websiteId, sessionId)
    
    # 修改信息映射结构，为邮箱和账号特殊处理
    info_mapping = [
        ('people_id', data, '👤*访客ID*', lambda x: x),
        ('state', data, '🔄*会话状态*', lambda x: x),
        ('email', metas, '📧*电子邮箱*', lambda x: f'`{x}`'),
    ]
    
    # 处理基本信息
    for key, source, prefix, formatter in info_mapping:
        if value := source.get(key):
            escaped_value = escape_markdown(formatter(value), preserve_backticks=('`' in formatter(value)))
            flow.append(f'{prefix}：{escaped_value}')
    
    # 处理元数据
    if meta_data := metas.get("data", {}):
        meta_mapping = [
            ('Account', '📧*用户账号*', lambda x: f'`{x}`'),
            ('SubscriptionName', '🪪*使用套餐*', lambda x: x),
            ('Plan', '🪪*使用套餐*', lambda x: x),
            ('ExpirationTime', '🪪*到期时间*', lambda x: x if x != "-" else "长期有效"),
            ('AccountCreated', '🪪*注册时间*', lambda x: x),
        ]
        
        for key, prefix, formatter in meta_mapping:
            if value := meta_data.get(key):
                escaped_value = escape_markdown(formatter(value), preserve_backticks=('`' in formatter(value)))
                flow.append(f'{prefix}：{escaped_value}')
                
        # 处理流量信息
        if 'UsedTraffic' in meta_data and ('AvailableTraffic' in meta_data or 'AllTraffic' in meta_data):
            used = escape_markdown(meta_data['UsedTraffic'])
            available = escape_markdown(meta_data.get('AvailableTraffic') or meta_data.get('AllTraffic'))
            flow.append(f"🗒*流量信息*：{used} / {available}")
    
    # 处理地理位置信息
    if device := metas.get("device"):
        if geolocation := device.get("geolocation"):
            geo_mapping = [
                ('country', '🇺🇸*国家*', lambda x: translation_dict.get(x, x)),
                ('region', '🏙️*地区*', lambda x: translation_dict.get(x, x)),
                ('city', '🌆*城市*', lambda x: translation_dict.get(x, x)),
            ]
            
            for key, prefix, translator in geo_mapping:
                if value := geolocation.get(key):
                    escaped_value = escape_markdown(translator(value))
                    flow.append(f'{prefix}：{escaped_value}')
                    
            if coords := geolocation.get("coordinates"):
                if all(key in coords for key in ['latitude', 'longitude']):
                    lat = escape_markdown(str(coords["latitude"]))
                    lon = escape_markdown(str(coords["longitude"]))
                    flow.append(f'📍*坐标*：{lat}, {lon}')
        
        # 处理系统信息
        if system := device.get("system"):
            if os_info := system.get("os"):
                os_name = escape_markdown(os_info.get("name", ""))
                os_version = escape_markdown(os_info.get("version", ""))
                if os_name:
                    flow.append(f'💻*操作系统*：{os_name} {os_version}')
                    
            if browser_info := system.get("browser"):
                browser_name = escape_markdown(browser_info.get("name", ""))
                browser_version = escape_markdown(browser_info.get("version", ""))
                if browser_name:
                    flow.append(f'🌐*浏览器*：{browser_name} {browser_version}')
    
    return '\n'.join(flow) if len(flow) > 1 else '\n'.join(flow + ['无额外信息'])


async def createSession(data):
    bot = callbackContext.bot
    botData = callbackContext.bot_data
    sessionId = data["session_id"]
    session = botData.get(sessionId)

    metas = getMetas(sessionId)
    print(f"获取到的元信息: {metas}")  # 打印获取到的元信息

    if session is None:
        enableAI = False if openai is None else True
        topic = await bot.create_forum_topic(
            groupId, data["user"]["nickname"])
        msg = await bot.send_message(
            groupId,
            metas,
            message_thread_id=topic.message_thread_id,
            reply_markup=changeButton(sessionId, enableAI),
            parse_mode='MarkdownV2'  # 添加这一行，指定使用 MarkdownV2 解析
        )
        botData[sessionId] = {
            'topicId': topic.message_thread_id,
            'messageId': msg.message_id,
            'enableAI': enableAI,
            'lastMetas': metas
        }
    else:
        try:
            await bot.edit_message_text(
                metas,
                chat_id=groupId,
                message_id=session['messageId'],
                reply_markup=changeButton(sessionId, session.get("enableAI", False)),
                parse_mode='MarkdownV2'  # 这里也添加 parse_mode
            )
            session['lastMetas'] = metas
        except Exception as error:
            print(f"发生未知错误: {error}")

# 新增函数：处理 Telegram 发来的图片
async def handle_telegram_photo(update, context):
    # 构造与 sendMessage 函数兼容的数据结构
    data = {
        "type": "photo",
        "photo": update.message.photo[-1],
        "session_id": context.user_data.get('current_session_id')  # 假设您在某处存储了当前会话ID
    }
    await sendMessage(data)


async def sendMessage(data):
    bot = callbackContext.bot
    botData = callbackContext.bot_data
    sessionId = data["session_id"]
    session = botData.get(sessionId)

    client.website.mark_messages_read_in_conversation(websiteId,sessionId,
        {"from": "user", "origin": "chat", "fingerprints": [data["fingerprint"]]}
    )

    if data["type"] == "text":
        # 检查消息内容是否为 111 或 222
        if data["content"] == '111' or data["content"] == '222':
            session["enableAI"] = (data["content"] == '222')
            await bot.edit_message_reply_markup(
                chat_id=groupId,
                message_id=session['messageId'],
                reply_markup=changeButton(sessionId, session["enableAI"])
            )
            # 发送提示消息给对方
            message_content = "AI客服已关闭" if data["content"] == '111' else "AI客服已开启"
            query = {
                "type": "text",
                "content": message_content,
                "from": "operator",
                "origin": "chat",
                "user": {
                    "nickname": '系统消息',
                    "avatar": avatars.get('system_message', 'https://example.com/system_avatar.png')
                }
            }
            client.website.send_message_in_conversation(websiteId, sessionId, query)
            return

            
        flow = []
        flow.append(f"🧾<b>消息推送</b>： {data['content']}")

        # 仅在会话的第一条消息时发送提示
        if openai is not None and session.get("first_message", True):  # 检查是否是会话的第一条消息
            session["first_message"] = False  # 标记为已发送提示
            hint_message = "您已接入智能客服 \n\n您可以输入 '111' 关闭AI客服，输入 '222' 开启AI客服。"
            hint_query = {
                "type": "text",
                "content": hint_message,
                "from": "operator",
                "origin": "chat",
                "user": {
                    "nickname": '系统消息',
                    "avatar": avatars.get('system_message', 'https://example.com/system_avatar.png')
                }
            }
            client.website.send_message_in_conversation(websiteId, sessionId, hint_query)  # 发送提示消息

        result, autoreply = getKey(data["content"])
        if result is True:
            flow.append("")
            flow.append(f"💡<b>自动回复</b>：{autoreply}")
        elif openai is not None and session["enableAI"] is True:
            response = openai.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": payload},
                    {"role": "user", "content": data["content"]}
                ]
            )
            autoreply = response.choices[0].message.content
            flow.append("")
            flow.append(f"💡<b>自动回复</b>：{autoreply}")
        
        if autoreply is not None:
            query = {
                "type": "text",
                "content": autoreply,
                "from": "operator",
                "origin": "chat",
                "user": {
                    "nickname": '智能客服',
                    "avatar": avatars.get('ai_agent', 'https://img.ixintu.com/download/jpg/20210125/8bff784c4e309db867d43785efde1daf_512_512.jpg')
                }
            }
            client.website.send_message_in_conversation(websiteId, sessionId, query)
        await bot.send_message(
            groupId,
            '\n'.join(flow),
            message_thread_id=session["topicId"]
        )
    elif data["type"] == "file" and str(data["content"]["type"]).count("image") > 0:
        # 处理从 Crisp 接收到的图片
        flow = []
        flow.append(f"📷 图片链接：{data['content']['url']}")

        # 发送图片到 Telegram 群组
        await bot.send_photo(
            groupId,
            data['content']['url'],
            caption='\n'.join(flow),
            parse_mode='HTML',
            message_thread_id=session["topicId"]
        )
    else:
        print("Unhandled Message Type : ", data["type"])

async def handle_telegram_photo(update, context):
    # 构造与 sendMessage 函数兼容的数据结构
    data = {
        "type": "photo",
        "photo": update.message.photo[-1],
        "session_id": context.user_data.get('current_session_id')
    }
    await sendMessage(data)


sio = socketio.AsyncClient(reconnection_attempts=5, logger=True)
# Def Event Handlers
@sio.on("connect")
async def connect():
    # 创建内联键盘按钮
    keyboard = [
        [
            InlineKeyboardButton("重启 Bot", callback_data="admin_restart_bot"),
            InlineKeyboardButton("新增关键字回复", callback_data="admin_keyword_add")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await callbackContext.bot.send_message(
        groupId,
        "已连接到 Crisp 服务器。",
        reply_markup=reply_markup
    )
    await sio.emit("authentication", {
        "tier": "plugin",
        "username": config["crisp"]["id"],
        "password": config["crisp"]["key"],
        "events": [
            "message:send",
            "session:set_data"
        ]})

@sio.on("unauthorized")
async def unauthorized(data):
    print('Unauthorized: ', data)
@sio.event
async def connect_error():
    print("The connection failed!")
    await callbackContext.bot.send_message(
        groupId,
        "无法连接到 Crisp 服务器。",
    )
    
@sio.event
async def disconnect():
    print("Disconnected from server.")
    await callbackContext.bot.send_message(
        groupId,
        "与 Crisp 服务器断开连接。",
    )
    
@sio.on("message:send")
async def messageForward(data):
    if data["website_id"] != websiteId:
        return
    await createSession(data)
    await sendMessage(data)


# Meow!
def getCrispConnectEndpoints():
    url = "https://api.crisp.chat/v1/plugin/connect/endpoints"

    authtier = base64.b64encode(
        (config["crisp"]["id"] + ":" + config["crisp"]["key"]).encode("utf-8")
    ).decode("utf-8")
    payload = ""
    headers = {"X-Crisp-Tier": "plugin", "Authorization": "Basic " + authtier}
    response = requests.request("GET", url, headers=headers, data=payload)
    endPoint = json.loads(response.text).get("data").get("socket").get("app")
    return endPoint

# Connecting to Crisp RTM(WSS) Server
async def exec(context: ContextTypes.DEFAULT_TYPE):
    global callbackContext
    callbackContext = context

    # 输出启用的图床服务信息
    print_enabled_image_services()

    # 添加处理图片的处理程序
    context.application.add_handler(MessageHandler(filters.PHOTO, handle_telegram_photo))

    # 发送启动消息到默认话题
    await callbackContext.bot.send_message(
        groupId,
        text="机器人已启动"
    )

    # await sendAllUnread()
    await sio.connect(
        getCrispConnectEndpoints(),
        transports="websocket",
        wait_timeout=10,
    )
    await sio.wait() 

# 添加新的回调处理函数
async def handle_admin_callback(update, context):
    """处理管理按钮的回调"""
    query = update.callback_query
    
    try:
        logging.info(f"收到管理回调: {query.data}")
        
        if query.data == "admin_restart_bot":
            keyboard = [[
                InlineKeyboardButton("确认重启", callback_data="admin_confirm_restart"),
                InlineKeyboardButton("取消", callback_data="admin_cancel_restart")
            ]]
            await query.message.edit_text(
                "确定要重启 Bot 吗？\n"
                "请选择以下操作：",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            await query.answer("请确认是否重启")
        
        elif query.data == "admin_confirm_restart":
            try:
                await query.answer("正在执行重启...")
                await query.message.edit_text("Bot 正在重启...")
                
                # 先执行 daemon-reload，然后强制结束进程并重启
                subprocess.run(['systemctl', 'daemon-reload'], check=True)
                subprocess.run(['systemctl', 'kill', '-s', 'SIGKILL', 'bot.service'], check=True)
                subprocess.Popen(['systemctl', 'start', 'bot.service'])
                
                # 立即退出当前进程
                sys.exit(0)
                
            except Exception as e:
                error_message = f"重启失败: {str(e)}"
                logging.error(error_message)
                await query.message.edit_text(error_message)
        
        elif query.data == "admin_cancel_restart":
            # 恢复原始按钮
            keyboard = [
                [
                    InlineKeyboardButton("重启 Bot", callback_data="admin_restart_bot"),
                    InlineKeyboardButton("新增关键字回复", callback_data="admin_keyword_add")
                ]
            ]
            await query.message.edit_text(
                "已连接到 Crisp 服务器。",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            await query.answer("已取消重启")
        
        elif query.data == "admin_keyword_add":
            # 保存当前消息的信息
            context.user_data['waiting_for'] = 'keyword'
            context.user_data['original_message_id'] = query.message.message_id
            context.user_data['original_chat_id'] = query.message.chat_id
            
            # 更新原消息为输入提示
            keyboard = [[
                InlineKeyboardButton("取消", callback_data="admin_cancel_keyword")
            ]]
            await query.message.edit_text(
                "请输入关键字(多个关键字用'|'分隔)：\n"
                "例如：你好|在吗\n\n"
                "注意：直接输入关键字，或点击取消返回",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            await query.answer("请输入关键字")
            
        elif query.data == "admin_cancel_keyword":
            # 恢复原始消息和按钮
            keyboard = [
                [
                    InlineKeyboardButton("重启 Bot", callback_data="admin_restart_bot"),
                    InlineKeyboardButton("新增关键字回复", callback_data="admin_keyword_add")
                ]
            ]
            await query.message.edit_text(
                "已连接到 Crisp 服务器。",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            # 清除状态
            context.user_data.clear()
            await query.answer("已取消操作")
            
    except Exception as e:
        error_message = f"处理回调时出错: {str(e)}"
        logging.error(error_message)
        try:
            await query.answer(error_message[:200])
            await query.message.reply_text(error_message)
        except:
            logging.error("无法发送错误消息")

# 修改关键字输入处理函数
async def handle_keyword_input(update, context):
    """处理用户输入的关键字和回复"""
    message = update.message
    
    # 检查是否是在正确的群组中
    if message.chat_id != config['bot']['groupId']:
        return
        
    # 检查是否在等待输入状态
    if 'waiting_for' not in context.user_data:
        return
    
    logging.info(f"处理关键字输入: {message.text}, 当前状态: {context.user_data['waiting_for']}")
    
    try:
        if context.user_data['waiting_for'] == 'keyword':
            # 保存关键字并等待回复内容
            context.user_data['keyword'] = message.text
            context.user_data['waiting_for'] = 'reply'
            
            # 更新原消息为等待回复状态
            keyboard = [[
                InlineKeyboardButton("取消", callback_data="admin_cancel_keyword")
            ]]
            try:
                await context.bot.edit_message_text(
                    chat_id=context.user_data['original_chat_id'],
                    message_id=context.user_data['original_message_id'],
                    text=f"✅ 已记录关键字：{message.text}\n"
                         f"请输入对应的回复内容：\n\n"
                         f"注意：直接输入回复内容，或点击取消返回",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            except Exception as e:
                logging.error(f"更新消息失败: {str(e)}")
            
            # 删除用户的输入消息
            try:
                await message.delete()
            except:
                pass
            
        elif context.user_data['waiting_for'] == 'reply':
            keyword = context.user_data['keyword']
            reply = message.text
            
            try:
                # 更新配置文件
                if 'autoreply' not in config:
                    config['autoreply'] = {}
                config['autoreply'][keyword] = reply
                
                # 保存到配置文件
                with open('config.yml', 'w', encoding='utf-8') as f:
                    yaml.dump(config, f, allow_unicode=True)
                
                # 更新原消息为成功状态
                keyboard = [
                    [
                        InlineKeyboardButton("重启 Bot", callback_data="admin_restart_bot"),
                        InlineKeyboardButton("新增关键字回复", callback_data="admin_keyword_add")
                    ]
                ]
                
                success_message = (
                    f"✅ 已成功添加新的关键字回复：\n\n"
                    f"🔑 关键字：{keyword}\n"
                    f"💬 回复内容：{reply}\n\n"
                    f"可以继续添加新的关键字回复或执行其他操作"
                )
                
                try:
                    await context.bot.edit_message_text(
                        chat_id=context.user_data['original_chat_id'],
                        message_id=context.user_data['original_message_id'],
                        text=success_message,
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
                except Exception as e:
                    if "Message is not modified" not in str(e):
                        logging.error(f"更新消息失败: {str(e)}")
                
                # 删除用户的输入消息
                try:
                    await message.delete()
                except:
                    pass
                
            except Exception as e:
                error_message = f"❌ 保存配置失败: {str(e)}"
                await context.bot.edit_message_text(
                    chat_id=context.user_data['original_chat_id'],
                    message_id=context.user_data['original_message_id'],
                    text=error_message,
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("重试", callback_data="admin_keyword_add"),
                        InlineKeyboardButton("取消", callback_data="admin_cancel_keyword")
                    ]])
                )
                logging.error(f"保存配置失败: {str(e)}")
            finally:
                # 清除用户状态
                context.user_data.clear()
                
    except Exception as e:
        error_message = f"处理关键字输入时出错: {str(e)}"
        logging.error(error_message)
        # 恢复原始按钮状态
        keyboard = [
            [
                InlineKeyboardButton("重启 Bot", callback_data="admin_restart_bot"),
                InlineKeyboardButton("新增关键字回复", callback_data="admin_keyword_add")
            ]
        ]
        await context.bot.edit_message_text(
            chat_id=context.user_data['original_chat_id'],
            message_id=context.user_data['original_message_id'],
            text=f"❌ 操作失败: {error_message}\n\n请重试",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        # 清除用户状态
        context.user_data.clear() 
