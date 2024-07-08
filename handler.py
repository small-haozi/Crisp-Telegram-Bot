import bot
import json
import base64
import socketio
import requests
from telegram.ext import ContextTypes

config = bot.config
client = bot.client
openai = bot.openai
changeButton = bot.changeButton
groupId = config["bot"]["groupId"]
websiteId = config["crisp"]["website"]
payload = config["openai"]["payload"]

def getKey(content: str):
    if len(config["autoreply"]) > 0:
        for x in config["autoreply"]:
            keyword = x.split("|")
            for key in keyword:
                if key in content:
                    return True, config["autoreply"][x]
    return False, None

def getMetas(sessionId):
    metas = client.website.get_conversation_metas(websiteId, sessionId)

    flow = ['📠<b>Crisp消息推送</b>','']
    if len(metas["email"]) > 0:
        email = metas["email"]
        flow.append(f'📧<b>电子邮箱</b>：{email}')
    if len(metas["data"]) > 0:
        if "Plan" in metas["data"]:
            Plan = metas["data"]["Plan"]
            flow.append(f"🪪<b>使用套餐</b>：{Plan}")
        if "UsedTraffic" in metas["data"] and "AllTraffic" in metas["data"]:
            UsedTraffic = metas["data"]["UsedTraffic"]
            AllTraffic = metas["data"]["AllTraffic"]
            flow.append(f"🗒<b>流量信息</b>：{UsedTraffic} / {AllTraffic}")
    if len(flow) > 2:
        return '\n'.join(flow)
    return '无额外信息'


async def createSession(data):
    bot = callbackContext.bot
    botData = callbackContext.bot_data
    sessionId = data["session_id"]
    session = botData.get(sessionId)

    metas = getMetas(sessionId)
    if session is None:
        enableAI = False if openai is None else True
        topic = await bot.create_forum_topic(
            groupId,data["user"]["nickname"])
        msg = await bot.send_message(
            groupId,
            metas,
            message_thread_id=topic.message_thread_id,
            reply_markup=changeButton(sessionId,enableAI)
            )
        botData[sessionId] = {
            'topicId': topic.message_thread_id,
            'messageId': msg.message_id,
            'enableAI': enableAI
        }
    else:
        try:
            await bot.edit_message_text(metas,groupId,session['messageId'])
            # 保留两个按钮
            await bot.edit_message_reply_markup(
                chat_id=groupId,
                message_id=session['messageId'],
                reply_markup=changeButton(sessionId, session.get("enableAI", False))
            )
        except Exception as error:
            print(error)

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
                    "avatar": 'https://example.com/system_avatar.png'
                }
            }
            client.website.send_message_in_conversation(websiteId, sessionId, query)
            return

            
        flow = ['📠<b>消息推送</b>','']
        flow.append(f"🧾<b>消息内容</b>：{data['content']}")

        # 仅在会话的第一条消息时发送提示
        if session.get("first_message", True):  # 检查是否是会话的第一条消息
            session["first_message"] = False  # 标记为已发送提示
            hint_message = "您已接入智能客服 \n\n您可以输入 '111' 关闭AI客服，输入 '222' 开启AI客服。"
            hint_query = {
                "type": "text",
                "content": hint_message,
                "from": "operator",
                "origin": "chat",
                "user": {
                    "nickname": '系统消息',
                    "avatar": 'https://example.com/system_avatar.png'
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
                    "avatar": 'https://img.ixintu.com/download/jpg/20210125/8bff784c4e309db867d43785efde1daf_512_512.jpg'
                }
            }
            client.website.send_message_in_conversation(websiteId, sessionId, query)
        await bot.send_message(
            groupId,
            '\n'.join(flow),
            message_thread_id=session["topicId"]
        )
    elif data["type"] == "file" and str(data["content"]["type"]).count("image") > 0:
        await bot.send_photo(
            groupId,
            data["content"]["url"],
            message_thread_id=session["topicId"]
        )
    else:
        print("Unhandled Message Type : ", data["type"])

sio = socketio.AsyncClient(reconnection_attempts=5, logger=True)
# Def Event Handlers
@sio.on("connect")
async def connect():
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
@sio.event
async def disconnect():
    print("Disconnected from server.")
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
    # await sendAllUnread()
    await sio.connect(
        getCrispConnectEndpoints(),
        transports="websocket",
        wait_timeout=10,
    )
    await sio.wait() 
