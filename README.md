# DeepSeek AI 聊天应用

自用基于DeepSeek API的聊天应用，提供简单易用的AI对话界面，同时确保API密钥安全。

## 特点

- 🔒 安全性：API密钥仅存储在用户浏览器中，不在服务器保存
- 💬 流畅的对话体验：支持Markdown和代码高亮
- 🌐 简单部署：基于Flask的轻量级服务
- 📱 响应式设计：适配各种设备尺寸
- 🔌 代理支持：配置代理解决网络连接问题

## 安装与使用

1. 克隆仓库
   ```
   git clone https://github.com/ghostdoglzd/MyChatApi.git
   cd MyChatApi
   ```

2. 安装依赖
   ```
   pip install flask requests tenacity
   ```

3. 运行服务
   ```
   python api.py
   ```

4. 在浏览器中访问 `http://127.0.0.1:5000`

## 使用方法

1. 在登录页面输入您的DeepSeek API密钥
2. 按照提示接受隐私政策
3. 开始与AI助手对话

## 网络连接问题

如果遇到连接DeepSeek API的问题，可以通过以下步骤配置代理：

1. 在聊天界面点击"设置"按钮
2. 勾选"使用代理"
3. 输入HTTP和HTTPS代理地址（例如：http://127.0.0.1:7890）
4. 保存设置并重试

## 隐私保障

- API密钥只存储在您的浏览器中，不会发送到我们的服务器存储
- 对话数据仅临时存储用于维持上下文，会话结束后自动删除
- 采用HTTPS确保传输过程安全

## 问题反馈

如果您遇到问题或有改进建议，请[提交issue](https://github.com/ghostdoglzd/MyChatApi/issues)。

## 许可证

MIT License