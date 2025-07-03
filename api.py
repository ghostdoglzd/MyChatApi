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
        response = requests.post(
            DEEPSEEK_API_URL,
            json=payload,
            headers=headers,
            timeout=120
        )
        response.raise_for_status()
        return response
    except requests.exceptions.HTTPError as e:
        app.logger.error(f"HTTPError: {e}")
        app.logger.error(f"Response status code: {e.response.status_code}")
        app.logger.error(f"Response content: {e.response.text}")
        raise

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
        app.logger.error(f"Request payload: {payload}")
        app.logger.error(f"Request headers: {headers}")
        
        inner_exception = getattr(e, "last_attempt", None)
        if inner_exception and hasattr(inner_exception, "exception"):
            inner_exc = inner_exception.exception()
            if isinstance(inner_exc, requests.exceptions.HTTPError):
                return jsonify({
                    "error": "DeepSeek API returned an error",
                    "details": f"HTTP Status: {inner_exc.response.status_code}, Response: {inner_exc.response.text}"
                }), 503
                
        return jsonify({
            "error": "Failed to connect to DeepSeek API after retries",
            "details": str(e)
        }), 503
    except requests.exceptions.ConnectionError as e:
        app.logger.error(f"ConnectionError: Unable to establish connection to DeepSeek API. Details: {str(e)}")
        app.logger.error(f"Request payload: {payload}")
        app.logger.error(f"Request headers: {headers}")
        return jsonify({
            "error": "Connection error occurred",
            "details": str(e)
        }), 503
    except requests.exceptions.Timeout:
        app.logger.error("TimeoutError: Request to DeepSeek API timed out.")
        return jsonify({"error": "Request timed out"}), 504
    except Exception as e:
        app.logger.error(f"Unexpected error: {str(e)}")
        return jsonify({
            "error": "An unexpected error occurred",
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