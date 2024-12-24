import bot
import json
import base64
import socketio
import requests
import logging
import io
import re
from location_names import translation_dict  # 导入词典文件

from telegram.ext import ContextTypes
from telegram.ext import MessageHandler, filters
from PIL import Image
from contextlib import contextmanager



config = bot.config
client = bot.client
openai = bot.openai
changeButton = bot.changeButton
groupId = config["bot"]["groupId"]
websiteId = config["crisp"]["website"]
payload = config["openai"]["payload"]
# 添加这一行来初始化avatars
avatars = config.get('avatars', {})


def find_emails(content):
    # 简单的邮箱识别逻辑
    words = content.split()
    emails = [word for word in words if '@' in word and '.' in word]
    return emails

def format_content(content):
    emails = find_emails(content)
    for email in emails:
        content = content.replace(email, f'`{email}`')
    return content

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
            "url": "https://telegra.ph/upload?source=bugtracker",
            "type": "telegraph",
            "enabled": enabled_services.get('telegraph', True)
        },
        {
            "url": "https://api.imgbb.com/1/upload",
            "type": "imgbb",
            "enabled": enabled_services.get('imgbb', True)
        },
        {
            "url": "https://file.sang.pub/api/upload",
            "type": "sang_pub",
            "enabled": enabled_services.get('sang_pub', False)
        },
        {
            "url": f"https://api.cloudinary.com/v1_1/{config.get('image_upload', {}).get('cloudinary', {}).get('cloud_name', '')}/image/upload",
            "type": "cloudinary",
            "enabled": enabled_services.get('cloudinary', False)
        }
    ]

    # 确保 image_data 是字节对象
    if isinstance(image_data, io.BytesIO):
        image_data = image_data.getvalue()
    elif not isinstance(image_data, bytes):
        raise ValueError("image_data 必须是 bytes 或 BytesIO 对象")

    # 检测图片格式
    try:
        img = Image.open(io.BytesIO(image_data))
        img_format = img.format.lower()
        img.close()
    except Exception as e:
        logging.error(f"无法检测图片格式: {str(e)}")
        img_format = 'jpeg'  # 默认假设为JPEG

    for api in apis:
        if not enabled_services.get(api["type"], False):
            logging.info(f"跳过已禁用的图床服务: {api['type']}")
            continue
        
        # 为每次尝试创建新的 BytesIO 对象
        image_io = io.BytesIO(image_data)
        try:
            
            if api["type"] == "telegraph":
                files = {'file': ('image.' + img_format, image_data, 'image/' + img_format)}
                response = requests.post(api["url"], files=files)
                response.raise_for_status()
                image_url = 'https://telegra.ph' + response.json()['src']
                logging.info(f"成功上传到 {api['type']}: {image_url}")
                return image_url

            elif api["type"] == "sang_pub":
                    files = {'file': (f'image.{img_format}', image_data, f'image/{img_format}')}
                    response = requests.post(api["url"], files=files, timeout=10)
                    response.raise_for_status()
                    # 直接使用响应文本作为图片URL
                    image_url = response.text.strip()
                    if not image_url or not image_url.startswith('http'):
                        raise ValueError(f"无效的图片URL: {image_url}")
                    logging.info(f"成功上传到 {api['type']}: {image_url}")
                    return image_url
                
            elif api["type"] == "imgbb":
                imgbb_api_key = config.get('image_upload', {}).get('imgbb_api_key')
                if not imgbb_api_key:
                    logging.warning("ImgBB API密钥未设置,跳过ImgBB上传")
                    continue
                
                files = {'image': (f'image.{img_format}', image_data, f'image/{img_format}')}
                params = {'key': imgbb_api_key}
                
                imgbb_expiration = config.get('image_upload', {}).get('imgbb_expiration', 0)
                if imgbb_expiration != 0:
                    params['expiration'] = imgbb_expiration
                
                response = requests.post(api["url"], files=files, params=params)
                response.raise_for_status()  # 这将在非200状态码时抛出异常
                image_url = response.json()['data']['url']
                logging.info(f"成功上传到 {api['type']}: {image_url}")
                return image_url

            elif api["type"] == "cloudinary":
                cloudinary_config = config.get('image_upload', {}).get('cloudinary', {})
                if not all([cloudinary_config.get('cloud_name'), cloudinary_config.get('upload_preset')]):
                    logging.warning("Cloudinary配置不完整,跳过Cloudinary上传")
                    continue
                
                try:
                    # 准备上传数据
                    data = {
                        "file": f"data:image/jpeg;base64,{base64.b64encode(image_data).decode('utf-8')}",
                        "upload_preset": cloudinary_config['upload_preset']
                    }
                    
                    response = requests.post(api["url"], data=data)
                    response.raise_for_status()
                    
                    upload_result = response.json()
                    image_url = upload_result['secure_url']
                    logging.info(f"成功上传到 {api['type']}: {image_url}")
                    return image_url
                except requests.exceptions.RequestException as e:
                    logging.error(f"上传到 Cloudinary 失败: {str(e)}")
                    if hasattr(e, 'response') and e.response is not None:
                        logging.error(f"错误详情: {e.response.text}")
        
        except requests.exceptions.RequestException as e:
            logging.error(f"上传到 {api['type']} 失败: {str(e)}")
        except Exception as e:
            logging.error(f"上传到 {api['type']} 时发生未知错误: {str(e)}")
        finally:
            image_io.close()
            
    raise Exception("所有启用的图片上传API都失败了")


def getKey(content: str):
    if len(config["autoreply"]) > 0:
        for x in config["autoreply"]:
            keyword = x.split("|")
            for key in keyword:
                if key in content:
                    return True, config["autoreply"][x]
    return False, None

def getMetas(sessionId):
    conversation = client.website.get_conversation(websiteId, sessionId)

    flow = ['📠*Crisp消息推送*']
    info_added = False

    if conversation.get("error"):
        flow.append('无法获取会话信息')
        return '\n'.join(flow)

    data = conversation.get("data", {})

    # 添加会话信息
    if data.get("people_id"):
        flow.append(f'👤*访客ID*：{data["people_id"]}')
        info_added = True

    if data.get("state"):
        flow.append(f'🔄*会话状态*：{data["state"]}')
        info_added = True

    metas = client.website.get_conversation_metas(websiteId, sessionId)

    if metas.get("email"):
        flow.append(f'📧*电子邮箱*： `{metas["email"]}`')
        info_added = True

    if metas.get("data"):
        if "Account" in metas["data"]:
            flow.append(f"📧*用户账号*： `{metas['data']['Account']}`")
            info_added = True
        if "SubscriptionName" in metas["data"] or "Plan" in metas["data"]:
            plan_name = metas["data"].get("SubscriptionName", metas["data"].get("Plan", ""))
            flow.append(f"🪪*使用套餐*：{plan_name}")
            info_added = True
        if "UsedTraffic" in metas["data"] and ("AvailableTraffic" in metas["data"] or "AllTraffic" in metas["data"]):
            available_traffic = metas["data"].get("AvailableTraffic", metas["data"].get("AllTraffic", ""))
            flow.append(f"🗒*流量信息*：{metas['data']['UsedTraffic']} / {available_traffic}")
            info_added = True
        if "SubscriptionName" in metas["data"]:
            if "ExpirationTime" in metas["data"] and metas["data"]["ExpirationTime"] != "-":
                flow.append(f"🪪*到期时间*：{metas['data']['ExpirationTime']}")
            else:
                flow.append("🪪*到期时间*：长期有效")
            info_added = True
        if "AccountCreated" in metas["data"]:
            flow.append(f"🪪*注册时间*：{metas['data']['AccountCreated']}")
            info_added = True
        

    # 获取地理位置
    if metas.get("device") and metas["device"].get("geolocation"):
        geolocation = metas["device"]["geolocation"]
        if geolocation.get("country"):
            country = geolocation["country"]
            # 使用词典进行翻译
            translated_country = translation_dict.get(country, country)
            flow.append(f'🇺🇸*国家*：{translated_country}')
            info_added = True
        if geolocation.get("region"):
            region = geolocation["region"]
            # 使用词典进行翻译
            translated_region = translation_dict.get(region, region)
            flow.append(f'🏙️*地区*：{translated_region}')
            info_added = True
        if geolocation.get("city"):
            city = geolocation["city"]
            # 使用词典进行翻译
            translated_city = translation_dict.get(city, city)
            flow.append(f'🌆*城市*：{translated_city}')
            info_added = True
        if geolocation.get("coordinates"):
            coords = geolocation["coordinates"]
            if coords.get("latitude") and coords.get("longitude"):
                flow.append(f'📍*坐标*：{coords["latitude"]}, {coords["longitude"]}')
                info_added = True

    if metas.get("device"):
        device = metas["device"]
        if device.get("system"):
            os_info = device["system"].get("os", {})
            if os_info.get("name"):
                flow.append(f'💻*操作系统*：{os_info["name"]} {os_info.get("version", "")}')
                info_added = True

            browser_info = device["system"].get("browser", {})
            if browser_info.get("name"):
                flow.append(f'🌐*浏览器*：{browser_info["name"]} {browser_info.get("version", "")}')
                info_added = True
    if not info_added:
        flow.append('无额外信息')

    return '\n'.join(flow)


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
            parse_mode='Markdown'
        )
        botData[sessionId] = {
            'topicId': topic.message_thread_id,
            'messageId': msg.message_id,
            'enableAI': enableAI,
            'lastMetas': metas  # 存储最后一次的元信息
        }
    else:
        # 移除元信息变化的检查条件
        try:
            await bot.edit_message_text(
                metas,
                chat_id=groupId,
                message_id=session['messageId'],
                reply_markup=changeButton(sessionId, session.get("enableAI", False)),
                parse_mode='Markdown'
            )
            session['lastMetas'] = metas  # 更新存储的元信息
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
        formatted_content = format_content(data['content'])
        flow.append(f"🧾*消息推送*： {formatted_content}")

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
            flow.append(f"💡*自动回复*：{autoreply}")
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
            flow.append(f"💡*自动回复*：{autoreply}")
        
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
            message_thread_id=session["topicId"],
            parse_mode='Markdown'
        )
    elif data["type"] == "file" and str(data["content"]["type"]).count("image") > 0:
        # 处理从 Crisp 接收到的图片
        flow = []

        # 发送图片到 Telegram 群组
        await bot.send_photo(
            groupId,
            data["content"]["url"],
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
    await callbackContext.bot.send_message(
        groupId,
        "已连接到 Crisp 服务器。",
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
