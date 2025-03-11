# Crisp Telegram Bot via Python

一个简单的项目 为了省点米子疯狂码代码

Python 版本需求 >= 3.9

## 常规使用
```
# apt install git 
git clone https://github.com/small-haozi/Crisp-Telegram-Bot.git
cd Crisp-Telegram-Bot
chmod +x crispbot.sh
./crispbot.sh
```

## docker使用
```
# apt install git 
git clone https://github.com/small-haozi/Crisp-Telegram-Bot.git
cd Crisp-Telegram-Bot
chmod +x docker-bot.sh
./docker-bot.sh
```
输入1创建bot
修改/opt/crisp/目录下的config【编号】【别名】
选择是否立刻构建  立即创建yes   
如果想手动仔细修改后创建选no 则
```
docker-compose up -d
```

## 申请 Telegram Bot Token

1. 私聊 [https://t.me/BotFather](https://https://t.me/BotFather)
2. 输入 `/newbot`，并为你的bot起一个**响亮**的名字
3. 接着为你的bot设置一个username，但是一定要以bot结尾，例如：`v2board_bot`
4. 最后你就能得到bot的token了，看起来应该像这样：`123456789:gaefadklwdqojdoiqwjdiwqdo`

## 申请 Crisp 以及 MarketPlace 插件

1. 注册 [https://app.crisp.chat/initiate/signup](https://app.crisp.chat/initiate/signup)
2. 完成注册后，网站ID在浏览器中即可找到，看起来应该像这样：`https://app.crisp.chat/settings/website/12345678-1234-1234-1234-1234567890ab/`
3. 其中 `12345678-1234-1234-1234-1234567890ab` 就是网站ID
4. 前往 MarketPlace， 需要重新注册账号 [https://marketplace.crisp.chat/](https://marketplace.crisp.chat/)
7. 需要 2 条read和write权限：`website:conversation:sessions` 和 `website:conversation:messages`
8. 保存后即可获得ID和Key，此时点击右上角 Install Plugin on Website 即可。


```
cp bot.service /etc/systemd/system/bot.service
sudo systemctl daemon-reload
sudo systemctl enable bot.service
sudo systemctl start bot.service
sudo systemctl restart bot.service
sudo systemctl stop bot.service
sudo systemctl status bot.service
```

