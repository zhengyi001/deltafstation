#!/usr/bin/env python3
"""
DeltaFStation 量化交易系统启动脚本
"""
import os
import sys

# 添加本地deltafq路径到Python路径
deltafq_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '../deltafq'))
if deltafq_path not in sys.path:
    sys.path.insert(0, deltafq_path)

# 设置环境变量
os.environ.setdefault('FLASK_ENV', 'development')
os.environ.setdefault('FLASK_APP', 'run.py')
os.environ.setdefault('PORT', '5001')
os.environ.setdefault('HOST', '0.0.0.0')
os.environ.setdefault('HTTP_PROXY', 'http://127.0.0.1:14076')
os.environ.setdefault('HTTPS_PROXY', 'http://127.0.0.1:14076')


def main():
    """主函数"""
    from backend.app import create_app

    # 创建应用
    app = create_app()

    # 获取配置
    port = int(os.environ.get('PORT'))
    host = os.environ.get('HOST')
    debug = os.environ.get('FLASK_ENV') == 'development'

    print("=" * 50)
    print("DeltaFStation 量化交易系统")
    print("=" * 50)
    print(f"启动地址: http://{host}:{port}")
    print(f"调试模式: {'开启' if debug else '关闭'}")
    print("=" * 50)

    # 启动应用
    app.run(host=host, port=port, debug=debug)


if __name__ == '__main__':
    main()
