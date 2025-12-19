# TG 频道自动签到

## 环境变量

- **TG_API_ID**：申请TG开发者可获取
- **TG_API_HASH**：申请TG开发者可获取
- **TG_BOT_TOKEN**：用于签到成功后发送TG通知
- **TG_CHAT_ID**：用于签到成功后发送TG通知
- **TG_CHANNEL**：需要登录的频道用户名，格式：`@username`
- **CHANNEL_BOT_ID**：频道签到机器人的ID

## TG登录验证文件：tg_session.session

此文件无法自动生成  
需要先在PC或VPS上执行py脚本，按提示输入 `电话` 和 `验证码`，才会生成这个文件  
然后将这个文件上传到仓库，和PY脚本同级目录  
后续执行脚本即可全自动化，无须人工干预
