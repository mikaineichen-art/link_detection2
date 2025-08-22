#!/usr/bin/env python3
"""
Alternative entry point for Railway deployment
"""

import os
from api_server import app

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))

