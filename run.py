#!/usr/bin/env python
"""
Entry point for EssentialPipeline
"""

import os
import sys

# Add the project root to Python path
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

from essentialpipeline.app import create_app

# Create and configure the app
app = create_app()

if __name__ == '__main__':
    # Run the application
    host = os.environ.get('HOST', '0.0.0.0')
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_DEBUG', 'True').lower() == 'true'
    
    print(f"Starting EssentialPipeline Pipeline Tool...")
    print(f"  Host: {host}")
    print(f"  Port: {port}")
    print(f"  Debug: {debug}")
    print(f"  Environment: {app.config.get('ENV', 'development')}")
    
    app.run(host=host, port=port, debug=debug)
