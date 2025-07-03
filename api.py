import time
from tenacity import retry, stop_after_attempt, wait_exponential, RetryError  # 导入RetryError
from flask import Flask, request, jsonify, render_template
import requests
import os
from datetime import datetime

app = Flask(__name__)

# 使用正确的DeepSeek API端点
DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"
# 从环境变量获取API密钥更安全
DEEPSEEK_API_KEY = ""

# 设置上下文最大长度
MAX_CONTEXT_LENGTH = 10

# 首页路由 - 提供聊天界面
@app.route('/')
def index():
    return render_template('index.html')

# 在ask_question函数中添加重试逻辑
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def call_deepseek_api(payload, headers):
    try:
        response = requests.post(
            DEEPSEEK_API_URL,
            json=payload,
            headers=headers,
            timeout=120  # 将超时时间延长到 120 秒
        )
        response.raise_for_status()  # 这里可能会引发HTTPError
        return response
    except requests.exceptions.HTTPError as e:
        app.logger.error(f"HTTPError: {e}")
        app.logger.error(f"Response status code: {e.response.status_code}")
        app.logger.error(f"Response content: {e.response.text}")
        raise  # 重新抛出异常，让重试机制处理

# 存储会话上下文
session_context = {}

# 问答API路由
@app.route('/ask', methods=['POST'])
def ask_question():
    try:
        # 获取请求中的问题
        data = request.json
        question = data.get('question')
        session_id = data.get('session_id', 'default')  # 使用会话ID区分不同会话
        if not question:
            return jsonify({"error": "Question is required"}), 400

        # 初始化会话上下文
        if session_id not in session_context:
            session_context[session_id] = []

        # 添加用户消息到上下文
        session_context[session_id].append({"role": "user", "content": question})

        # 限制上下文长度
        if len(session_context[session_id]) > MAX_CONTEXT_LENGTH:
            session_context[session_id] = session_context[session_id][-MAX_CONTEXT_LENGTH:]

        # 准备请求头
        headers = {
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            "Content-Type": "application/json"
        }
        
        # 构建符合DeepSeek API要求的请求体
        payload = {
            "model": "deepseek-chat",
            "messages": session_context[session_id],  # 包含上下文消息
            "temperature": 0.7,
            "max_tokens": 4000,  # 降低token限制，避免超过API限制
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
        # print(f"answer: {answer}")


        
        # 返回答案给前端
        return jsonify({
            "answer": answer,
            "raw_response": response_data  # 添加原始响应数据
        })

    except RetryError as e:
        app.logger.error(f"RetryError: Failed to connect to DeepSeek API after retries. Details: {str(e)}")
        app.logger.error(f"Request payload: {payload}")
        app.logger.error(f"Request headers: {headers}")
        
        # 检查是否是HTTP错误并提供更详细的错误信息
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

if __name__ == '__main__':
    app.run(debug=True)