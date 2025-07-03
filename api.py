import time
from tenacity import retry, stop_after_attempt, wait_exponential, RetryError
from flask import Flask, request, jsonify, render_template, redirect, url_for, session
import requests
import os
from datetime import datetime
import secrets

app = Flask(__name__)
app.secret_key = secrets.token_hex(16)

# 使用正确的DeepSeek API端点
DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"
# 移除API密钥存储，密钥将完全由客户端存储

# 设置上下文最大长度
MAX_CONTEXT_LENGTH = 10

# 存储会话上下文
session_context = {}

# 代理设置 - 默认不使用代理
proxy_settings = {
    'use_proxy': False,
    'http_proxy': None,
    'https_proxy': None
}

# 登录页面路由 - 作为网站入口点
@app.route('/')
def login():
    return render_template('login.html')

# 处理API密钥验证
@app.route('/verify_key', methods=['POST'])
def verify_key():
    # 只验证API密钥格式，不存储
    api_key = request.json.get('api_key')
    if not api_key or not api_key.startswith('sk-'):
        return jsonify({"success": False, "error": "无效的API密钥格式"}), 400
    
    # 生成唯一的会话ID，用于管理上下文，但不关联密钥
    session_id = secrets.token_urlsafe(16)
    session['session_id'] = session_id
    
    return jsonify({"success": True, "session_id": session_id})

# 聊天页面路由
@app.route('/chat')
def chat():
    session_id = session.get('session_id')
    if not session_id:
        # 如果没有会话ID，重定向到登录页面
        return redirect(url_for('login'))
    
    return render_template('index.html')

# 首页路由 - 重定向到登录或聊天页面
@app.route('/index')
def index():
    session_id = session.get('session_id')
    if not session_id:
        return redirect(url_for('login'))
    return redirect(url_for('chat'))

# 在ask_question函数中添加重试逻辑
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def call_deepseek_api(payload, headers):
    try:
        # 根据代理设置决定是否使用代理
        proxies = None
        if proxy_settings['use_proxy'] and (proxy_settings['http_proxy'] or proxy_settings['https_proxy']):
            proxies = {
                'http': proxy_settings['http_proxy'],
                'https': proxy_settings['https_proxy']
            }
            app.logger.info(f"使用代理: {proxies}")
        else:
            # 明确指定不使用代理
            proxies = {'http': None, 'https': None}
            app.logger.info("不使用代理连接")
            
        response = requests.post(
            DEEPSEEK_API_URL,
            json=payload,
            headers=headers,
            proxies=proxies,  # 添加代理配置
            timeout=120
        )
        response.raise_for_status()
        return response
    except requests.exceptions.ProxyError as e:
        app.logger.error(f"代理错误: {e}")
        # 尝试不使用代理再次连接
        app.logger.info("尝试不使用代理直接连接...")
        response = requests.post(
            DEEPSEEK_API_URL,
            json=payload,
            headers=headers,
            proxies={'http': None, 'https': None},
            timeout=120
        )
        response.raise_for_status()
        return response
    except requests.exceptions.HTTPError as e:
        app.logger.error(f"HTTPError: {e}")
        app.logger.error(f"Response status code: {e.response.status_code}")
        app.logger.error(f"Response content: {e.response.text}")
        raise

# 设置代理路由
@app.route('/set_proxy', methods=['POST'])
def set_proxy():
    data = request.json
    proxy_settings['use_proxy'] = data.get('use_proxy', False)
    proxy_settings['http_proxy'] = data.get('http_proxy')
    proxy_settings['https_proxy'] = data.get('https_proxy')
    
    app.logger.info(f"代理设置已更新: 使用代理: {proxy_settings['use_proxy']}, HTTP代理: {proxy_settings['http_proxy']}, HTTPS代理: {proxy_settings['https_proxy']}")
    
    return jsonify({"success": True})

# 问答API路由
@app.route('/ask', methods=['POST'])
def ask_question():
    try:
        # 获取请求中的问题、会话ID和API密钥
        data = request.json
        question = data.get('question')
        api_key = data.get('api_key')  # 从请求中获取API密钥
        session_id = session.get('session_id')
        
        # 验证必要参数
        if not question:
            return jsonify({"error": "问题不能为空"}), 400
        if not api_key:
            return jsonify({"error": "API密钥不能为空"}), 401
        if not session_id:
            return jsonify({"error": "无效的会话，请重新登录"}), 401
        
        # 初始化会话上下文
        if session_id not in session_context:
            session_context[session_id] = []

        # 添加用户消息到上下文
        session_context[session_id].append({"role": "user", "content": question})

        # 限制上下文长度
        if len(session_context[session_id]) > MAX_CONTEXT_LENGTH:
            session_context[session_id] = session_context[session_id][-MAX_CONTEXT_LENGTH:]

        # 准备请求头 - 使用客户端提供的API密钥
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        # 构建符合DeepSeek API要求的请求体
        payload = {
            "model": "deepseek-chat",
            "messages": session_context[session_id],
            "temperature": 0.7,
            "max_tokens": 4000,
            "stream": False
        }
        
        # 记录请求时间
        start_time = time.time()

        # 调用DeepSeek API
        response = call_deepseek_api(payload, headers)
        
        # 记录响应时间
        api_time = time.time() - start_time
        app.logger.info(f"API响应时间: {api_time:.2f}秒")

        # 检查API响应
        if response.status_code != 200:
            error_msg = response.json().get("error", {}).get("message", "Unknown error")
            return jsonify({
                "error": "Failed to get response from DeepSeek API",
                "details": error_msg
            }), response.status_code

        # 解析API响应
        response_data = response.json()
        answer = response_data["choices"][0]["message"]["content"]

        # 添加AI回复到上下文
        session_context[session_id].append({"role": "assistant", "content": answer})
        
        # 返回答案给前端
        return jsonify({
            "answer": answer,
            "raw_response": response_data
        })

    except RetryError as e:
        app.logger.error(f"RetryError: Failed to connect to DeepSeek API after retries. Details: {str(e)}")
        
        # 打印更多异常信息以帮助调试
        inner_exception = getattr(e, "last_attempt", None)
        if inner_exception and hasattr(inner_exception, "exception"):
            inner_exc = inner_exception.exception()
            app.logger.error(f"底层异常类型: {type(inner_exc).__name__}")
            app.logger.error(f"底层异常内容: {str(inner_exc)}")
            
            if isinstance(inner_exc, requests.exceptions.ProxyError):
                return jsonify({
                    "error": "代理连接失败",
                    "details": "连接DeepSeek API时发生代理错误，请检查代理设置或尝试直接连接。"
                }), 503
            if isinstance(inner_exc, requests.exceptions.HTTPError):
                return jsonify({
                    "error": "DeepSeek API返回错误",
                    "details": f"HTTP状态: {inner_exc.response.status_code}, 响应: {inner_exc.response.text}"
                }), 503
                
        return jsonify({
            "error": "多次尝试连接DeepSeek API失败",
            "details": "请检查网络连接、代理设置或API状态。"
        }), 503
    except requests.exceptions.ConnectionError as e:
        app.logger.error(f"ConnectionError: Unable to establish connection to DeepSeek API. Details: {str(e)}")
        return jsonify({
            "error": "连接错误",
            "details": "无法建立与DeepSeek API的连接，请检查网络或代理设置。"
        }), 503
    except requests.exceptions.Timeout:
        app.logger.error("TimeoutError: Request to DeepSeek API timed out.")
        return jsonify({"error": "请求超时", "details": "连接DeepSeek API超时，请稍后再试。"}), 504
    except Exception as e:
        app.logger.error(f"Unexpected error: {str(e)}")
        app.logger.error(f"Error type: {type(e).__name__}")
        # 记录详细的调用堆栈
        import traceback
        app.logger.error(f"堆栈跟踪: {traceback.format_exc()}")
        return jsonify({
            "error": "发生未预期的错误",
            "details": str(e)
        }), 500

# 登出路由 - 清除会话
@app.route('/logout')
def logout():
    session_id = session.get('session_id')
    if session_id and session_id in session_context:
        del session_context[session_id]
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(debug=True)